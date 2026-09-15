import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from justtest_observability.http_server import build_server
from justtest_observability.storage import SQLiteTelemetryStore


class HTTPServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteTelemetryStore(Path(self.tmp.name) / "telemetry.db")
        self.server = build_server("127.0.0.1", 0, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.close()
        self.tmp.cleanup()

    def test_ingest_health_query_and_entities(self) -> None:
        body = json.dumps(
            {
                "records": [
                    {
                        "kind": "metric",
                        "name": "request.count",
                        "service": "checkout",
                        "host": "local",
                        "timestamp": 123.0,
                        "tags": {"env": "test"},
                        "payload": {"value": 1, "origin_container_id": "ctr-1"},
                    }
                ]
            }
        ).encode()
        request = Request(
            self.base + "/v1/telemetry",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            result = json.loads(response.read())
            self.assertEqual(response.status, 202)
            self.assertEqual(result["accepted"], 1)

        with urlopen(self.base + "/health", timeout=3) as response:
            health = json.loads(response.read())
            self.assertEqual(health["stored"], 1)
            self.assertEqual(health["accepted"], 1)

        with urlopen(
            self.base + "/v1/query?kind=metric&service=checkout", timeout=3
        ) as response:
            query = json.loads(response.read())
            self.assertEqual(query["records"][0]["name"], "request.count")

        with urlopen(self.base + "/v1/entities?type=service", timeout=3) as response:
            entities = json.loads(response.read())
            self.assertEqual(len(entities["entities"]), 1)
            self.assertEqual(entities["entities"][0]["id"], "checkout")
            self.assertEqual(entities["entities"][0]["tags"]["env"], "test")

        with urlopen(
            self.base + "/v1/entities?type=container&seen_after=100", timeout=3
        ) as response:
            entities = json.loads(response.read())
            self.assertEqual(entities["entities"][0]["id"], "ctr-1")

    def test_rejects_invalid_payload_and_entity_query(self) -> None:
        request = Request(
            self.base + "/v1/telemetry",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request, timeout=3)
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.base + "/v1/entities?type=pod", timeout=3)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
