# justtest observability platform

This repository is being built as a clean-room, dependency-light observability platform. The long-term target is a cohesive product spanning metrics, logs, traces/APM, processes, containers, network telemetry, alerting, service/entity discovery, local durability, reliable forwarding, and explorer/query UX. It does not copy proprietary Datadog source code or claim product equivalence.

## Current vertical slice

The first milestone provides a shared telemetry envelope for `metric`, `log`, `trace`, `event`, and `service_check` records, durable SQLite storage, a bounded local ingestion/query HTTP API, a CLI, a failure-isolated collector runtime with shared resource tags, a native host collector, and Windows/Linux CI.

The local API intentionally binds to loopback by default. There is no authentication layer yet, so do not expose it to an untrusted network.

```bash
python -m pip install -e .
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

Collect host telemetry once without third-party monitoring dependencies:

```bash
python -m justtest_observability --database ./var/telemetry.db --tag env=dev collect-once
```

Or continuously collect it every 15 seconds:

```bash
python -m justtest_observability --database ./var/telemetry.db --tag env=dev agent
```

Query locally persisted telemetry:

```bash
python -m justtest_observability --database ./var/telemetry.db query --kind metric --service demo
```

HTTP endpoints currently available are `GET /health`, `POST /v1/telemetry`, and `GET /v1/query`. Requests are capped at 4 MiB and ingestion batches at 1,000 records.

## Engineering direction

The core design is deliberately small: standard-library HTTP and SQLite first, then add collectors, transport/spooling, common entity/tag semantics, signal-specific indexing, OpenTelemetry/OpenMetrics/DogStatsD-compatible ingestion where useful, and richer explorer/query surfaces. New abstractions should earn their complexity through an implemented capability and test coverage.
