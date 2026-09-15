import socket
import tempfile
import time
import unittest
from pathlib import Path

from justtest_observability.dogstatsd import (
    DogStatsDParseError,
    DogStatsDServer,
    parse_message,
)
from justtest_observability.resource import ResourceContext
from justtest_observability.storage import SQLiteTelemetryStore


class DogStatsDParserTests(unittest.TestCase):
    def test_parses_packed_metric_with_metadata(self) -> None:
        records = parse_message(
            "request.latency:12.5:15|d|@0.5|#env:test,service:api|c:abc123|card:high"
        )
        self.assertEqual(len(records), 2)
        self.assertEqual([record.payload["value"] for record in records], [12.5, 15.0])
        self.assertEqual(records[0].payload["metric_type"], "distribution")
        self.assertEqual(records[0].payload["sample_rate"], 0.5)
        self.assertEqual(records[0].payload["origin_container_id"], "abc123")
        self.assertEqual(records[0].payload["cardinality"], "high")
        self.assertEqual(records[0].tags["env"], "test")
        self.assertEqual(records[0].service, "api")

    def test_set_keeps_string_value_and_rejects_packing(self) -> None:
        record = parse_message("users.unique:alice|s|#env:test")[0]
        self.assertEqual(record.payload["value"], "alice")
        with self.assertRaises(DogStatsDParseError):
            parse_message("users.unique:alice:bob|s")

    def test_parses_utf8_event_by_byte_lengths(self) -> None:
        title = "部署完成"
        text = "版本 v2\\nhealthy"
        message = (
            f"_e{{{len(title.encode('utf-8'))},{len(text.encode('utf-8'))}}}:"
            f"{title}|{text}|d:1700000000|h:web-1|t:success|#env:prod,service:web"
        )
        record = parse_message(message)[0]
        self.assertEqual(record.kind, "event")
        self.assertEqual(record.name, title)
        self.assertEqual(record.payload["text"], "版本 v2\nhealthy")
        self.assertEqual(record.payload["alert_type"], "success")
        self.assertEqual(record.timestamp, 1700000000.0)
        self.assertEqual(record.host, "web-1")
        self.assertEqual(record.service, "web")

    def test_parses_service_check(self) -> None:
        record = parse_message(
            "_sc|redis.can_connect|2|d:1700000001|h:cache-1|#env:prod,service:cache|m:timeout"
        )[0]
        self.assertEqual(record.kind, "service_check")
        self.assertEqual(record.payload["status"], 2)
        self.assertEqual(record.payload["status_name"], "critical")
        self.assertEqual(record.payload["message"], "timeout")
        self.assertEqual(record.service, "cache")

    def test_rejects_invalid_metric(self) -> None:
        with self.assertRaises(DogStatsDParseError):
            parse_message("bad metric:1|g")
        with self.assertRaises(DogStatsDParseError):
            parse_message("metric:1|g|@1.5")


class DogStatsDServerTests(unittest.TestCase):
    def test_udp_server_persists_valid_messages_and_isolates_invalid_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                server = DogStatsDServer(
                    store,
                    port=0,
                    resource=ResourceContext(host="agent-host", tags={"region": "test"}),
                )
                server.start()
                try:
                    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    try:
                        sender.sendto(
                            b"demo.count:2|c|#service:api\ninvalid\ndemo.gauge:3|g",
                            server.address,
                        )
                    finally:
                        sender.close()
                    deadline = time.monotonic() + 2.0
                    while time.monotonic() < deadline and store.count() < 2:
                        time.sleep(0.01)
                    self.assertEqual(store.count(), 2)
                    count = store.query(name="demo.count")[0].record
                    self.assertEqual(count.host, "agent-host")
                    self.assertEqual(count.tags["region"], "test")
                    status = server.snapshot()
                    self.assertEqual(status.datagrams, 1)
                    self.assertEqual(status.messages, 3)
                    self.assertEqual(status.records, 2)
                    self.assertEqual(status.errors, 1)
                finally:
                    server.stop()


if __name__ == "__main__":
    unittest.main()
