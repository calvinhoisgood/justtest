import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from justtest_observability.forwarder import DurableHTTPForwarder
from justtest_observability.model import TelemetryRecord
from justtest_observability.storage import SQLiteTelemetryStore


class _Receiver(BaseHTTPRequestHandler):
    attempts = 0
    bodies: list[dict[str, object]] = []
    fail_first = True

    def do_POST(self) -> None:
        type(self).attempts += 1
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        type(self).bodies.append(body)
        if type(self).fail_first and type(self).attempts == 1:
            self.send_response(503)
        else:
            self.send_response(202)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, _format: str, *args: object) -> None:
        pass


class DurableForwarderTests(unittest.TestCase):
    def setUp(self) -> None:
        _Receiver.attempts = 0
        _Receiver.bodies = []
        _Receiver.fail_first = True
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_failed_delivery_does_not_advance_cursor_and_success_does(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "telemetry.db"
            with SQLiteTelemetryStore(db) as store:
                ids = store.append_many(
                    [
                        TelemetryRecord(kind="metric", name="a", payload={"value": 1}),
                        TelemetryRecord(kind="event", name="b", payload={"text": "ok"}),
                    ]
                )
                endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/telemetry"
                forwarder = DurableHTTPForwarder(store, endpoint, consumer="primary")

                with self.assertRaises(Exception):
                    forwarder.forward_once()
                self.assertEqual(store.delivery_cursor("primary"), 0)
                self.assertEqual(forwarder.snapshot().errors, 1)

                self.assertEqual(forwarder.forward_once(), 2)
                self.assertEqual(store.delivery_cursor("primary"), ids[-1])
                self.assertEqual(forwarder.forward_once(), 0)
                self.assertEqual(_Receiver.attempts, 2)
                self.assertEqual(len(_Receiver.bodies[-1]["records"]), 2)

                new_id = store.append_many(
                    [TelemetryRecord(kind="metric", name="c", payload={"value": 3})]
                )[0]
                self.assertEqual(forwarder.forward_once(), 1)
                self.assertEqual(store.delivery_cursor("primary"), new_id)
                self.assertEqual(_Receiver.bodies[-1]["records"][0]["name"], "c")

    def test_delivery_cursor_is_monotonic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                store.ack_delivery("remote", 10)
                store.ack_delivery("remote", 3)
                self.assertEqual(store.delivery_cursor("remote"), 10)

    def test_rejects_single_record_larger_than_body_limit_without_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                store.append_many(
                    [TelemetryRecord(kind="log", name="app", payload={"message": "x" * 5000})]
                )
                endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/telemetry"
                forwarder = DurableHTTPForwarder(
                    store,
                    endpoint,
                    consumer="small",
                    max_body_bytes=1024,
                )
                with self.assertRaises(ValueError):
                    forwarder.forward_once()
                self.assertEqual(store.delivery_cursor("small"), 0)
                self.assertEqual(_Receiver.attempts, 0)


class ForwarderEndToEndTests(unittest.TestCase):
    def test_forwards_into_native_ingestion_api(self) -> None:
        from justtest_observability.http_server import build_server

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with SQLiteTelemetryStore(root / "source.db") as source, SQLiteTelemetryStore(
                root / "dest.db"
            ) as dest:
                source.append_many(
                    [
                        TelemetryRecord(
                            kind="metric",
                            name="end.to.end",
                            service="api",
                            tags={"env": "test"},
                            payload={"value": 7},
                        )
                    ]
                )
                server = build_server("127.0.0.1", 0, dest)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    forwarder = DurableHTTPForwarder(
                        source,
                        f"http://127.0.0.1:{server.server_port}/v1/telemetry",
                        consumer="e2e",
                    )
                    self.assertEqual(forwarder.forward_once(), 1)
                    received = dest.query(name="end.to.end")
                    self.assertEqual(len(received), 1)
                    self.assertEqual(received[0].record.service, "api")
                    self.assertEqual(received[0].record.tags["env"], "test")
                    self.assertEqual(source.delivery_cursor("e2e"), 1)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
