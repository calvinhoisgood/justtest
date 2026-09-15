from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

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


def test_dashboard_is_served_as_product_ui(tmp_path):
    with SQLiteTelemetryStore(tmp_path / "telemetry.db") as store:
        server, thread = _start_server(store)
        try:
            response = urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=2)
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"] == "text/html; charset=utf-8"
            assert "Content-Security-Policy" in response.headers
            assert "justtest Observability" in body
            assert "Observability Overview" in body
            assert "Infrastructure" in body
            assert "Services" in body
            assert "Telemetry Explorer" in body
            assert "/v1/overview" in body
        finally:
            _stop_server(server, thread)


def test_overview_reports_signal_and_entity_counts(tmp_path):
    with SQLiteTelemetryStore(tmp_path / "telemetry.db") as store:
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
            assert body["total_records"] == 3
            assert body["records_by_kind"] == {"log": 1, "metric": 2}
            assert body["entities_by_type"] == {
                "container": 1,
                "host": 1,
                "service": 1,
            }
            assert body["latest_timestamp"] is not None
        finally:
            _stop_server(server, thread)


def test_dashboard_stays_loadable_but_overview_honors_auth(tmp_path):
    with SQLiteTelemetryStore(tmp_path / "telemetry.db") as store:
        server, thread = _start_server(store, auth_token="ui-test-value")
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/", timeout=2) as response:
                assert response.status == 200
                assert b"Connect to protected API" in response.read()

            with pytest.raises(HTTPError) as exc_info:
                urlopen(base + "/v1/overview", timeout=2)
            assert exc_info.value.code == 401

            request = Request(
                base + "/v1/overview",
                headers={"Authorization": "Bearer ui-test-value"},
            )
            with urlopen(request, timeout=2) as response:
                assert response.status == 200
                assert json.loads(response.read())["total_records"] == 0
        finally:
            _stop_server(server, thread)
