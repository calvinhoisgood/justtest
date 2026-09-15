import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from justtest_observability.model import TelemetryRecord
from justtest_observability.storage import SQLiteTelemetryStore


class EntityCatalogTests(unittest.TestCase):
    def test_telemetry_updates_host_service_and_container_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                store.append_many(
                    [
                        TelemetryRecord(
                            kind="metric",
                            name="requests",
                            timestamp=20.0,
                            service="api",
                            host="node-a",
                            tags={
                                "env": "prod",
                                "region": "sg",
                                "request_id": "high-cardinality-ignored",
                            },
                            payload={
                                "value": 1,
                                "origin_container_id": "container-123",
                                "cardinality": "high",
                            },
                        )
                    ]
                )
                entities = {
                    (item.entity_type, item.entity_id): item for item in store.query_entities()
                }
                self.assertEqual(
                    set(entities),
                    {
                        ("host", "node-a"),
                        ("service", "api"),
                        ("container", "container-123"),
                    },
                )
                self.assertEqual(entities[("service", "api")].tags["env"], "prod")
                self.assertNotIn("request_id", entities[("service", "api")].tags)
                self.assertEqual(
                    entities[("container", "container-123")].attributes["cardinality"],
                    "high",
                )

    def test_entity_lifetime_handles_out_of_order_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                store.append_many(
                    [
                        TelemetryRecord(
                            kind="event",
                            name="new",
                            timestamp=20.0,
                            service="api",
                            tags={"version": "2"},
                            payload={},
                        ),
                        TelemetryRecord(
                            kind="event",
                            name="old",
                            timestamp=10.0,
                            service="api",
                            tags={"env": "prod", "version": "1"},
                            payload={},
                        ),
                    ]
                )
                service = store.query_entities(entity_type="service")[0]
                self.assertEqual(service.first_seen, 10.0)
                self.assertEqual(service.last_seen, 20.0)
                self.assertEqual(service.tags["version"], "2")
                self.assertEqual(service.tags["env"], "prod")

    def test_schema_upgrade_backfills_entities_from_existing_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "telemetry.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '2')"
                )
                connection.execute(
                    """
                    CREATE TABLE telemetry_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        kind TEXT NOT NULL,
                        name TEXT NOT NULL,
                        service TEXT,
                        host TEXT,
                        tags_json TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO telemetry_records(
                        timestamp, kind, name, service, host, tags_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        42.0,
                        "metric",
                        "legacy.metric",
                        "legacy-api",
                        "legacy-host",
                        json.dumps({"env": "legacy"}),
                        json.dumps({"value": 1, "origin_container_id": "legacy-container"}),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            with SQLiteTelemetryStore(path) as store:
                entities = {
                    (item.entity_type, item.entity_id): item for item in store.query_entities()
                }
                self.assertIn(("host", "legacy-host"), entities)
                self.assertIn(("service", "legacy-api"), entities)
                self.assertIn(("container", "legacy-container"), entities)
                self.assertEqual(entities[("service", "legacy-api")].tags["env"], "legacy")

    def test_entity_filtering_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                store.append_many(
                    [
                        TelemetryRecord(
                            kind="event", name="a", timestamp=10.0, host="old", payload={}
                        ),
                        TelemetryRecord(
                            kind="event", name="b", timestamp=30.0, host="new", payload={}
                        ),
                    ]
                )
                rows = store.query_entities(entity_type="host", seen_after=20.0, limit=1)
                self.assertEqual([row.entity_id for row in rows], ["new"])
                with self.assertRaises(ValueError):
                    store.query_entities(entity_type="pod")


if __name__ == "__main__":
    unittest.main()
