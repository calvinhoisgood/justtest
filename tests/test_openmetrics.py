import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from justtest_observability.openmetrics import (
    OpenMetricsCollector,
    OpenMetricsParseError,
    parse_exposition,
)
from justtest_observability.resource import ResourceContext
from justtest_observability.runtime import CollectorRuntime
from justtest_observability.storage import SQLiteTelemetryStore


class OpenMetricsParserTests(unittest.TestCase):
    def test_parses_types_labels_escapes_and_timestamps(self) -> None:
        records = parse_exposition(
            '# TYPE http_requests_total counter\n'
            'http_requests_total{service="api",method="post",path="a\\\\b\\nline"} 3 1700000000123\n'
            '# TYPE latency_seconds histogram\n'
            'latency_seconds_bucket{le="0.5",service="api"} 4\n'
            'latency_seconds_sum{service="api"} 1.25\n'
            '# EOF\n',
            common_tags={"env": "test"},
        )
        self.assertEqual(len(records), 3)
        first = records[0]
        self.assertEqual(first.payload["metric_type"], "counter")
        self.assertEqual(first.timestamp, 1700000000.123)
        self.assertEqual(first.tags["env"], "test")
        self.assertEqual(first.tags["path"], "a\\b\nline")
        self.assertEqual(first.service, "api")
        self.assertEqual(records[1].payload["metric_type"], "histogram")
        self.assertEqual(records[2].payload["metric_type"], "histogram")

    def test_rejects_non_finite_malformed_and_excess_samples(self) -> None:
        with self.assertRaises(OpenMetricsParseError):
            parse_exposition("broken_metric NaN\n")
        with self.assertRaises(OpenMetricsParseError):
            parse_exposition('metric{bad="unterminated} 1\n')
        with self.assertRaises(OpenMetricsParseError):
            parse_exposition("a 1\nb 2\n", max_samples=1)


class _MetricsHandler(BaseHTTPRequestHandler):
    body = b'# TYPE demo gauge\ndemo{service="catalog"} 7\n'

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, _format: str, *args: object) -> None:
        pass


class OpenMetricsCollectorTests(unittest.TestCase):
    def test_scrapes_into_existing_runtime_and_resource_pipeline(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MetricsHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                    collector = OpenMetricsCollector(
                        f"http://127.0.0.1:{server.server_port}/metrics",
                        name="openmetrics-test",
                        tags={"integration": "prometheus"},
                    )
                    runtime = CollectorRuntime(
                        store,
                        [collector],
                        resource=ResourceContext(host="agent-host", tags={"region": "sg"}),
                    )
                    self.assertEqual(runtime.collect_once(), 1)
                    record = store.query(name="demo")[0].record
                    self.assertEqual(record.payload["value"], 7.0)
                    self.assertEqual(record.service, "catalog")
                    self.assertEqual(record.host, "agent-host")
                    self.assertEqual(record.tags["region"], "sg")
                    self.assertEqual(record.tags["integration"], "prometheus")
                    services = store.query_entities(entity_type="service")
                    self.assertEqual(services[0].entity_id, "catalog")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
