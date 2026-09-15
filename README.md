# justtest observability platform

This repository is being built as a clean-room observability platform with a product experience, not only an agent. The long-term target is a cohesive SaaS-style system spanning dashboards/explorers, metrics, logs, traces/APM, processes, containers, network telemetry, alerting, service/entity discovery, local durability, reliable forwarding, and centralized multi-user operation. It does not copy proprietary Datadog source code or claim product equivalence.

## Current vertical slice

The current milestone now has a first product-facing Web UI as well as the agent/backend foundation. It provides:

- a dark local observability dashboard with Overview, Infrastructure, Services, and Telemetry Explorer views;
- live summary cards, signal distribution, recent host metric sparklines, entity tables, telemetry search/filtering, and 15-second refresh;
- a shared telemetry envelope for `metric`, `log`, `trace`, `event`, and `service_check` records;
- native host telemetry on Linux and Windows without a third-party monitoring agent;
- loopback DogStatsD UDP ingestion for common metrics, packed values, tags, events, service checks, container origin, and cardinality metadata;
- bounded Prometheus/OpenMetrics text scraping for common metric, label, type, and timestamp forms;
- durable SQLite/WAL telemetry storage plus a host/service/container entity catalog;
- a local HTTP ingestion/query/overview API and CLI query surfaces;
- optional bearer authentication for `/v1/*` API routes;
- durable ordered HTTP forwarding backed by persistent consumer cursors;
- per-collector failure isolation and shared resource enrichment;
- Windows/Linux CI on Python 3.11 and 3.13;
- a Windows PyInstaller workflow that builds and smoke-tests a single-file `JustTestObservability.exe` artifact.

The local HTTP API/UI and DogStatsD endpoint intentionally bind to loopback by default. Bearer authentication is available for the `/v1/*` routes, but TLS termination is not implemented. The static dashboard shell and `/health` remain public; when API auth is enabled, the browser prompts for the bearer token and keeps it only in that browser tab. Do not expose the service directly to an untrusted network without HTTPS termination and appropriate access controls.

## Run the local agent and Web UI

```bash
python -m pip install -e .
python -m justtest_observability \
  --database ./var/telemetry.db \
  --tag env=dev \
  agent
```

The agent now runs the complete local vertical slice by default: native host collection every 15 seconds, DogStatsD on `127.0.0.1:8125`, and the API/Web UI on `http://127.0.0.1:8127/`.

Open the dashboard in a browser:

```text
http://127.0.0.1:8127/
```

Or ask the CLI to open it automatically:

```bash
python -m justtest_observability --database ./var/telemetry.db agent --open-browser
```

Disable individual local listeners when required:

```bash
python -m justtest_observability agent --no-dogstatsd
python -m justtest_observability agent --no-api
```

## Windows executable

The `windows-exe` GitHub Actions workflow builds a single-file `JustTestObservability.exe` with PyInstaller and smoke-tests both the CLI and the Web UI on a native Windows runner. The workflow uploads `JustTestObservability-windows-x64` as an Actions artifact.

The packaged Windows entry point is designed for a desktop-like first run: launching the EXE with no arguments starts the local agent and opens the dashboard. Command-line arguments remain available for explicit server/agent configuration.

## DogStatsD ingestion

Send a DogStatsD metric without installing another monitoring agent:

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(
    b"demo.request.count:1|c|#env:dev,service:demo",
    ("127.0.0.1", 8125),
)
sock.close()
```

A standalone DogStatsD receiver is also available:

```bash
python -m justtest_observability --database ./var/telemetry.db dogstatsd
```

## Scrape Prometheus/OpenMetrics endpoints

Add one or more scrape targets to the normal agent lifecycle:

```bash
python -m justtest_observability \
  --database ./var/telemetry.db \
  --tag env=dev \
  agent \
  --openmetrics-url http://127.0.0.1:9100/metrics \
  --openmetrics-url http://127.0.0.1:8080/metrics
```

The scraper intentionally implements a bounded common text-exposition subset rather than claiming complete Prometheus/OpenMetrics compatibility. It supports normal metric names, quoted label values and escapes, `TYPE` metadata for counter/gauge/histogram/summary/untyped samples, optional millisecond timestamps, and `# EOF`. Unsupported or malformed input fails that collector cycle without stopping other collectors. Response size and sample count are bounded.

To run host and scrape collectors once:

```bash
python -m justtest_observability \
  --database ./var/telemetry.db \
  collect-once \
  --openmetrics-url http://127.0.0.1:9100/metrics
```

## Local HTTP API and queries

A standalone UI/API server remains available when collection should run in another process:

```bash
python -m justtest_observability --database ./var/telemetry.db serve --open-browser
```

In another shell, ingest one metric:

```bash
python - <<'PY'
import json
from urllib.request import Request, urlopen

body = json.dumps({"records": [{
    "kind": "metric",
    "name": "demo.request.count",
    "service": "demo",
    "host": "demo-host",
    "tags": {"env": "dev"},
    "payload": {"value": 1}
}]}).encode()
request = Request(
    "http://127.0.0.1:8127/v1/telemetry",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urlopen(request).read().decode())
PY
```

Query locally persisted telemetry:

```bash
python -m justtest_observability \
  --database ./var/telemetry.db \
  query --kind metric --service demo
```

Query the durable entity catalog behind the Infrastructure and Services views:

```bash
python -m justtest_observability \
  --database ./var/telemetry.db \
  entities --type service
```

HTTP endpoints currently available are `GET /`, `GET /ui`, `GET /health`, `GET /v1/overview`, `POST /v1/telemetry`, `GET /v1/query`, and `GET /v1/entities`. HTTP ingestion requests are capped at 4 MiB and ingestion batches at 1,000 records.

## Durable forwarding

A local store can forward telemetry to another compatible HTTP ingestion endpoint. The consumer cursor is persisted in the same SQLite database and advances only after an HTTP 2xx response:

```bash
python -m justtest_observability \
  --database ./var/telemetry.db \
  forward \
  --endpoint http://127.0.0.1:9000/v1/telemetry
```

Or run forwarding alongside the normal agent:

```bash
python -m justtest_observability \
  --database ./var/telemetry.db \
  agent \
  --forward-url http://127.0.0.1:9000/v1/telemetry
```

Forwarding is ordered and at-least-once while source records remain in the local database. A remote accept followed by a lost response can cause a duplicate on retry; there is not yet a remote idempotency protocol or dead-letter queue. Do not prune unacknowledged source telemetry if it still needs to be delivered.

## Engineering direction

The UI is now a first-class product surface. Near-term work will deepen it alongside the backend rather than treating it as an afterthought: richer metric charts and time ranges, process/container inventory, logs, traces/APM, service topology, alerting, saved dashboards, configuration, centralized storage, authentication/authorization, tenant/user concepts, and deployment packaging. The implementation remains capability-driven: abstractions should earn their complexity through a working product capability and test coverage.
