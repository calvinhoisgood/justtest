import tempfile
import unittest
from pathlib import Path

from justtest_observability.model import TelemetryRecord
from justtest_observability.resource import ResourceContext
from justtest_observability.runtime import CollectorRuntime
from justtest_observability.storage import SQLiteTelemetryStore


class GoodCollector:
    name = "good"

    def collect(self):
        return [TelemetryRecord(kind="metric", name="good.metric", payload={"value": 1})]


class BadCollector:
    name = "bad"

    def collect(self):
        raise RuntimeError("boom")


class CollectorRuntimeTests(unittest.TestCase):
    def test_isolates_collector_failures_and_persists_successes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                runtime = CollectorRuntime(
                    store,
                    [BadCollector(), GoodCollector()],
                    resource=ResourceContext(host="test-host", tags={"env": "test"}),
                )
                self.assertEqual(runtime.collect_once(), 1)
                records = store.query(name="good.metric")
                self.assertEqual(records[0].record.host, "test-host")
                self.assertEqual(records[0].record.tags["env"], "test")
                status = runtime.snapshot()
                self.assertEqual(status["bad"].errors, 1)
                self.assertIn("RuntimeError", status["bad"].last_error or "")
                self.assertEqual(status["good"].records, 1)

    def test_rejects_duplicate_collector_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                with self.assertRaises(ValueError):
                    CollectorRuntime(store, [GoodCollector(), GoodCollector()])


if __name__ == "__main__":
    unittest.main()
