# justtest observability platform

This repository is being built as a clean-room, dependency-light observability platform. The long-term target is a cohesive product spanning metrics, logs, traces/APM, processes, containers, network telemetry, alerting, service/entity discovery, local durability, reliable forwarding, and explorer/query UX. It does not copy proprietary Datadog source code or claim product equivalence.

## Current vertical slice

The current milestone is an agent-shaped observability foundation rather than a single profiler. It provides:

- a shared telemetry envelope for `metric`, `log`, `trace`, `event`, and `service_check` records;
- native host telemetry on Linux and Windows without a third-party monitoring agent;
- loopback DogStatsD UDP ingestion for common metrics, packed values, tags, events, service checks, container origin, and cardinality metadata;
- bounded Prometheus/OpenMetrics text scraping for common metric, label, type, and timestamp forms;
- durable SQLite/WAL telemetry storage plus a host/service/container entity catalog;
- a loopback HTTP ingestion/query API and CLI query surfaces;
- durable ordered HTTP forwarding backed by persistent consumer cursors;
- per-collector failure isolation and shared resource enrichment;
- Windows/Linux CI on Python 3.11 and 3.13.

The local HTTP API and DogStatsD endpoint intentionally bind to loopback by default. There is no authentication or TLS termination layer yet, so do not expose them directly to an untrusted network.

## Run the local agent

```bash
python -m pip install -e .
python -m justtest_observability \
  --database ./var/telemetry.db \
  --tag env=dev \
  agent
```

The agent collects native host metrics every 15 seconds and listens for DogStatsD on `127.0.0.1:8125` by default. Disable the UDP receiver with `--no-dogstatsd` when the port should not be opened.

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

Run the local ingestion/query API:

```bash
python -m justtest_observability --database ./var/telemetry.db serve
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

Query the durable entity catalog used as the basis for future Infrastructure, Service, and Container Explorer surfaces:

```bash
python -m justtest_observability \
  --database ./var/telemetry.db \
  entities --type service
```

HTTP endpoints currently available are `GET /health`, `POST /v1/telemetry`, `GET /v1/query`, and `GET /v1/entities`. HTTP ingestion requests are capped at 4 MiB and ingestion batches at 1,000 records.

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

The design stays deliberately dependency-light and capability-driven: standard-library networking and SQLite first, then deepen workload/process/container collection, logs, traces/APM, common entity/tag semantics, reliable transport, authentication/TLS/configuration, signal-specific indexing, alerting, and richer explorer/query surfaces. New abstractions should earn their complexity through an implemented capability and test coverage.
