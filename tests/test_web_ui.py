from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from justtest_observability.http_server import build_server
from justtest_observability.model import TelemetryRecord
from justtest_observability.storage import SQLiteTelemetryStore


def _start_server(store: SQLiteTelemetryStore, *, auth_token: str | None = None):
    server = build_server("127.0.0.1", 0, store, auth_token=auth_token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


class WebUIDashboardTests(unittest.TestCase):
    def test_dashboard_is_served_as_product_ui(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with SQLiteTelemetryStore(Path(temp_dir) / "telemetry.db") as store:
                server, thread = _start_server(store)
                try:
                    response = urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=2)
                    body = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200)
                    self.assertEqual(
                        response.headers["Content-Type"], "text/html; charset=utf-8"
                    )
                    self.assertIn("Content-Security-Policy", response.headers)
                    self.assertIn("justtest Observability", body)
                    self.assertIn("Observability Overview", body)
                    self.assertIn("Infrastructure", body)
                    self.assertIn("Services", body)
                    self.assertIn("Telemetry Explorer", body)
                    self.assertIn("/v1/overview", body)
                finally:
                    _stop_server(server, thread)

    def test_overview_reports_signal_and_entity_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with SQLiteTelemetryStore(Path(temp_dir) / "telemetry.db") as store:
                store.append_many(
                    [
                        TelemetryRecord(
                            kind="metric",
                            name="system.cpu.logical_count",
                            host="host-a",
                            tags={"env": "dev"},
                            payload={"value": 8, "metric_type": "gauge"},
                        ),
                        TelemetryRecord(
                            kind="log",
                            name="request.log",
                            host="host-a",
                            service="checkout",
                            tags={"env": "dev"},
                            payload={"message": "ok"},
                        ),
                        TelemetryRecord(
                            kind="metric",
                            name="container.cpu",
                            host="host-a",
                            service="checkout",
                            tags={"env": "dev"},
                            payload={"value": 1.25, "origin_container_id": "container-a"},
                        ),
                    ]
                )
                server, thread = _start_server(store)
                try:
                    with urlopen(
                        f"http://127.0.0.1:{server.server_port}/v1/overview", timeout=2
                    ) as response:
                        body = json.loads(response.read())
                    self.assertEqual(body["total_records"], 3)
                    self.assertEqual(body["records_by_kind"], {"log": 1, "metric": 2})
                    self.assertEqual(
                        body["entities_by_type"],
                        {"container": 1, "host": 1, "service": 1},
                    )
                    self.assertIsNotNone(body["latest_timestamp"])
                finally:
                    _stop_server(server, thread)

    def test_dashboard_stays_loadable_but_overview_honors_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with SQLiteTelemetryStore(Path(temp_dir) / "telemetry.db") as store:
                server, thread = _start_server(store, auth_token="ui-test-value")
                base = f"http://127.0.0.1:{server.server_port}"
                try:
                    with urlopen(base + "/", timeout=2) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"Connect to protected API", response.read())

                    with self.assertRaises(HTTPError) as caught:
                        urlopen(base + "/v1/overview", timeout=2)
                    self.assertEqual(caught.exception.code, 401)

                    request = Request(
                        base + "/v1/overview",
                        headers={"Authorization": "Bearer ui-test-value"},
                    )
                    with urlopen(request, timeout=2) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(json.loads(response.read())["total_records"], 0)
                finally:
                    _stop_server(server, thread)


if __name__ == "__main__":
    unittest.main()
