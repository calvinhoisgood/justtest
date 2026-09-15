from __future__ import annotations

import argparse
import json
from pathlib import Path

from .http_server import build_server
from .storage import SQLiteTelemetryStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="justtest observability platform")
    parser.add_argument("--database", default="./var/telemetry.db", help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the local telemetry ingestion/query API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8127)

    query = subparsers.add_parser("query", help="query locally persisted telemetry")
    query.add_argument("--kind")
    query.add_argument("--service")
    query.add_argument("--host")
    query.add_argument("--name")
    query.add_argument("--limit", type=int, default=100)
    query.add_argument("--before-id", type=int)

    subparsers.add_parser("status", help="print local store status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database = Path(args.database)
    with SQLiteTelemetryStore(database) as store:
        if args.command == "serve":
            server = build_server(args.host, args.port, store)
            try:
                print(f"listening on http://{args.host}:{server.server_port}")
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
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
    return 2
