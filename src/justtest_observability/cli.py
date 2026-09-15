from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from pathlib import Path

from .collectors import HostCollector
from .dogstatsd import DogStatsDServer
from .forwarder import DurableHTTPForwarder
from .http_server import TelemetryHTTPServer, build_server
from .openmetrics import OpenMetricsCollector
from .resource import ResourceContext
from .runtime import CollectorRuntime
from .storage import SQLiteTelemetryStore


def _tag(value: str) -> tuple[str, str]:
    key, separator, tag_value = value.partition("=")
    if not separator or not key.strip():
        raise argparse.ArgumentTypeError("tags must use key=value syntax")
    return key.strip(), tag_value.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="justtest observability platform")
    parser.add_argument("--database", default="./var/telemetry.db", help="SQLite database path")
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        type=_tag,
        metavar="KEY=VALUE",
        help="common tag added to locally collected telemetry; may be repeated",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the observability Web UI and local API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8127)
    serve.add_argument("--auth-token", help="optional bearer token required by /v1 routes")
    serve.add_argument("--open-browser", action="store_true", help="open the Web UI in a browser")

    dogstatsd = subparsers.add_parser("dogstatsd", help="run the local DogStatsD UDP ingestion endpoint")
    dogstatsd.add_argument("--host", default="127.0.0.1")
    dogstatsd.add_argument("--port", type=int, default=8125)

    forward = subparsers.add_parser("forward", help="durably forward stored telemetry over HTTP")
    forward.add_argument("--endpoint", required=True)
    forward.add_argument("--consumer", default="default-http")
    forward.add_argument("--batch-size", type=int, default=500)
    forward.add_argument("--timeout", type=float, default=5.0)
    forward.add_argument("--interval", type=float, default=2.0)
    forward.add_argument("--bearer-token", help="optional bearer token for the remote endpoint")
    forward.add_argument("--once", action="store_true")

    query = subparsers.add_parser("query", help="query locally persisted telemetry")
    query.add_argument("--kind")
    query.add_argument("--service")
    query.add_argument("--host")
    query.add_argument("--name")
    query.add_argument("--limit", type=int, default=100)
    query.add_argument("--before-id", type=int)

    entities = subparsers.add_parser(
        "entities", help="query discovered host, service, and container entities"
    )
    entities.add_argument(
        "--type", dest="entity_type", choices=("host", "service", "container")
    )
    entities.add_argument("--seen-after", type=float)
    entities.add_argument("--limit", type=int, default=100)

    subparsers.add_parser("status", help="print local store status")
    collect_once = subparsers.add_parser(
        "collect-once", help="run configured local and scrape collectors once and exit"
    )
    collect_once.add_argument("--openmetrics-url", action="append", default=[])
    collect_once.add_argument("--openmetrics-timeout", type=float, default=5.0)

    agent = subparsers.add_parser(
        "agent", help="run collectors, receivers, API and the local observability Web UI"
    )
    agent.add_argument("--interval", type=float, default=15.0)
    agent.add_argument("--dogstatsd-host", default="127.0.0.1")
    agent.add_argument("--dogstatsd-port", type=int, default=8125)
    agent.add_argument("--api-host", default="127.0.0.1")
    agent.add_argument("--api-port", type=int, default=8127)
    agent.add_argument("--api-auth-token", help="optional bearer token required by /v1 routes")
    agent.add_argument("--open-browser", action="store_true", help="open the Web UI in a browser")
    agent.add_argument("--forward-url")
    agent.add_argument("--forward-consumer", default="default-http")
    agent.add_argument("--forward-batch-size", type=int, default=500)
    agent.add_argument("--forward-timeout", type=float, default=5.0)
    agent.add_argument("--forward-interval", type=float, default=2.0)
    agent.add_argument("--forward-bearer-token", help="optional bearer token for forwarding")
    agent.add_argument("--openmetrics-url", action="append", default=[])
    agent.add_argument("--openmetrics-timeout", type=float, default=5.0)
    agent.add_argument(
        "--no-dogstatsd",
        dest="dogstatsd",
        action="store_false",
        help="disable the DogStatsD UDP receiver",
    )
    agent.add_argument(
        "--no-api",
        dest="api",
        action="store_false",
        help="disable the local HTTP API and Web UI",
    )
    agent.set_defaults(dogstatsd=True, api=True)
    return parser


def _resource(tags: list[tuple[str, str]]) -> ResourceContext:
    return ResourceContext.local(dict(tags))


def _runtime(
    store: SQLiteTelemetryStore,
    resource: ResourceContext,
    *,
    openmetrics_urls: list[str] | None = None,
    openmetrics_timeout: float = 5.0,
) -> CollectorRuntime:
    collectors = [HostCollector()]
    for index, url in enumerate(openmetrics_urls or (), start=1):
        collectors.append(
            OpenMetricsCollector(
                url,
                name=f"openmetrics-{index}",
                timeout=openmetrics_timeout,
            )
        )
    return CollectorRuntime(store, collectors, resource=resource)


def _dashboard_url(server: TelemetryHTTPServer) -> str:
    try:
        host, port = server.server_address[:2]
    except (AttributeError, TypeError, ValueError):
        # Test doubles and adapter servers may expose only server_port.
        host, port = "127.0.0.1", server.server_port
    shown_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else str(host)
    return f"http://{shown_host}:{int(port)}/"


def _maybe_open_browser(url: str, enabled: bool) -> None:
    if not enabled:
        return
    try:
        webbrowser.open(url)
    except Exception as exc:
        print(f"warning: could not open browser: {exc}")


def _run_dogstatsd(
    store: SQLiteTelemetryStore,
    resource: ResourceContext,
    *,
    host: str,
    port: int,
) -> int:
    server = DogStatsDServer(store, host=host, port=port, resource=resource)
    server.start()
    try:
        bound_host, bound_port = server.address
        print(f"DogStatsD listening on udp://{bound_host}:{bound_port}")
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database = Path(args.database)
    with SQLiteTelemetryStore(database) as store:
        if args.command == "serve":
            server = build_server(args.host, args.port, store, auth_token=args.auth_token)
            url = _dashboard_url(server)
            try:
                print(f"Observability UI: {url}")
                _maybe_open_browser(url, args.open_browser)
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        if args.command == "dogstatsd":
            return _run_dogstatsd(
                store,
                _resource(args.tag),
                host=args.host,
                port=args.port,
            )
        if args.command == "forward":
            forwarder = DurableHTTPForwarder(
                store,
                args.endpoint,
                consumer=args.consumer,
                batch_size=args.batch_size,
                timeout=args.timeout,
                bearer_token=args.bearer_token,
            )
            if args.once:
                delivered = forwarder.forward_once()
                print(
                    json.dumps(
                        {
                            "delivered": delivered,
                            "consumer": forwarder.consumer,
                            "last_acked_id": store.delivery_cursor(forwarder.consumer),
                        }
                    )
                )
                return 0
            try:
                forwarder.run_forever(interval=args.interval)
            except KeyboardInterrupt:
                pass
            return 0
        if args.command == "status":
            print(json.dumps({"database": str(database), "stored": store.count()}))
            return 0
        if args.command == "query":
            rows = store.query(
                kind=args.kind,
                service=args.service,
                host=args.host,
                name=args.name,
                limit=args.limit,
                before_id=args.before_id,
            )
            for item in rows:
                record = item.record
                print(
                    json.dumps(
                        {
                            "id": item.id,
                            "timestamp": record.timestamp,
                            "kind": record.kind,
                            "name": record.name,
                            "service": record.service,
                            "host": record.host,
                            "tags": dict(record.tags),
                            "payload": dict(record.payload),
                        },
                        separators=(",", ":"),
                    )
                )
            return 0
        if args.command == "entities":
            rows = store.query_entities(
                entity_type=args.entity_type,
                seen_after=args.seen_after,
                limit=args.limit,
            )
            for item in rows:
                print(
                    json.dumps(
                        {
                            "type": item.entity_type,
                            "id": item.entity_id,
                            "first_seen": item.first_seen,
                            "last_seen": item.last_seen,
                            "tags": dict(item.tags),
                            "attributes": dict(item.attributes),
                        },
                        separators=(",", ":"),
                    )
                )
            return 0
        if args.command == "collect-once":
            runtime = _runtime(
                store,
                _resource(args.tag),
                openmetrics_urls=args.openmetrics_url,
                openmetrics_timeout=args.openmetrics_timeout,
            )
            persisted = runtime.collect_once()
            print(json.dumps({"collected": persisted, "stored": store.count()}))
            return 0
        if args.command == "agent":
            resource = _resource(args.tag)
            runtime = _runtime(
                store,
                resource,
                openmetrics_urls=args.openmetrics_url,
                openmetrics_timeout=args.openmetrics_timeout,
            )
            dogstatsd_server: DogStatsDServer | None = None
            api_server: TelemetryHTTPServer | None = None
            api_thread: threading.Thread | None = None
            forwarder: DurableHTTPForwarder | None = None
            forward_stop = threading.Event()
            forward_thread: threading.Thread | None = None
            if args.forward_url:
                forwarder = DurableHTTPForwarder(
                    store,
                    args.forward_url,
                    consumer=args.forward_consumer,
                    batch_size=args.forward_batch_size,
                    timeout=args.forward_timeout,
                    bearer_token=args.forward_bearer_token,
                )
            try:
                if args.api:
                    api_server = build_server(
                        args.api_host,
                        args.api_port,
                        store,
                        auth_token=args.api_auth_token,
                    )
                    api_thread = threading.Thread(
                        target=api_server.serve_forever,
                        name="telemetry-http",
                        daemon=True,
                    )
                    api_thread.start()
                    url = _dashboard_url(api_server)
                    print(f"Observability UI: {url}")
                    _maybe_open_browser(url, args.open_browser)
                if args.dogstatsd:
                    dogstatsd_server = DogStatsDServer(
                        store,
                        host=args.dogstatsd_host,
                        port=args.dogstatsd_port,
                        resource=resource,
                    )
                    dogstatsd_server.start()
                if forwarder is not None:
                    forward_thread = threading.Thread(
                        target=forwarder.run_forever,
                        kwargs={"interval": args.forward_interval, "stop_event": forward_stop},
                        name="telemetry-forwarder",
                        daemon=True,
                    )
                    forward_thread.start()
                runtime.run_forever(interval=args.interval)
            except KeyboardInterrupt:
                pass
            finally:
                forward_stop.set()
                if forward_thread is not None:
                    forward_thread.join(timeout=max(args.forward_timeout + 1.0, 2.0))
                if dogstatsd_server is not None:
                    dogstatsd_server.stop()
                if api_server is not None:
                    api_server.shutdown()
                    api_server.server_close()
                if api_thread is not None:
                    api_thread.join(timeout=2.0)
            return 0
    return 2
