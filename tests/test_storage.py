import tempfile
import unittest
from pathlib import Path

from justtest_observability.model import TelemetryRecord
from justtest_observability.storage import SQLiteTelemetryStore


class SQLiteTelemetryStoreTests(unittest.TestCase):
    def test_persists_and_filters_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.db"
            with SQLiteTelemetryStore(path) as store:
                ids = store.append_many(
                    [
                        TelemetryRecord(
                            kind="metric",
                            name="system.cpu",
                            service="api",
                            host="host-a",
                            timestamp=100.0,
                            tags={"env": "test"},
                            payload={"value": 42.0},
                        ),
                        TelemetryRecord(
                            kind="log",
                            name="app.log",
                            service="worker",
                            host="host-a",
                            timestamp=101.0,
                            payload={"message": "done"},
                        ),
                    ]
                )
                self.assertEqual(len(ids), 2)
                rows = store.query(kind="metric", service="api")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].record.payload["value"], 42.0)
            with SQLiteTelemetryStore(path) as reopened:
                self.assertEqual(reopened.count(), 2)

    def test_prunes_old_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                store.append_many(
                    [
                        TelemetryRecord(kind="event", name="old", timestamp=10.0, payload={}),
                        TelemetryRecord(kind="event", name="new", timestamp=20.0, payload={}),
                    ]
                )
                self.assertEqual(store.prune_older_than(15.0), 1)
                self.assertEqual(store.query()[0].record.name, "new")


if __name__ == "__main__":
    unittest.main()
