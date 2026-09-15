from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .entity import EntitySnapshot, derive_entities
from .model import TelemetryRecord

_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class StoredTelemetryRecord:
    id: int
    record: TelemetryRecord


class SQLiteTelemetryStore:
    """Durable local telemetry store with bounded query and delivery primitives."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "SQLiteTelemetryStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            version_row = self._connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            try:
                previous_version = int(version_row["value"]) if version_row is not None else 0
            except (TypeError, ValueError):
                previous_version = 0
            self._connection.execute("""CREATE TABLE IF NOT EXISTS telemetry_records (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, service TEXT, host TEXT, tags_json TEXT NOT NULL, payload_json TEXT NOT NULL)""")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry_records(timestamp DESC, id DESC)")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_kind_time ON telemetry_records(kind, timestamp DESC)")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_service_time ON telemetry_records(service, timestamp DESC)")
            self._connection.execute("""CREATE TABLE IF NOT EXISTS delivery_cursors (consumer TEXT PRIMARY KEY, last_id INTEGER NOT NULL)""")
            self._connection.execute("""CREATE TABLE IF NOT EXISTS entities (entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL, tags_json TEXT NOT NULL, attributes_json TEXT NOT NULL, PRIMARY KEY(entity_type, entity_id))""")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen DESC)")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_entities_type_seen ON entities(entity_type, last_seen DESC)")
            if previous_version < 3:
                rows = self._connection.execute("SELECT id, timestamp, kind, name, service, host, tags_json, payload_json FROM telemetry_records ORDER BY id ASC").fetchall()
                for row in rows:
                    for entity in derive_entities(self._decode(row).record):
                        self._upsert_entity(entity)
            self._connection.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)", (str(_SCHEMA_VERSION),))

    def append_many(self, records: Iterable[TelemetryRecord]) -> list[int]:
        rows = list(records)
        if not rows:
            return []
        ids: list[int] = []
        with self._lock, self._connection:
            for record in rows:
                cursor = self._connection.execute("INSERT INTO telemetry_records(timestamp, kind, name, service, host, tags_json, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)", (record.timestamp, record.kind, record.name, record.service, record.host, json.dumps(record.tags, sort_keys=True, separators=(",", ":")), json.dumps(record.payload, sort_keys=True, separators=(",", ":"))))
                ids.append(int(cursor.lastrowid))
                for entity in derive_entities(record):
                    self._upsert_entity(entity)
        return ids

    def _upsert_entity(self, entity: EntitySnapshot) -> None:
        row = self._connection.execute("SELECT first_seen, last_seen, tags_json, attributes_json FROM entities WHERE entity_type = ? AND entity_id = ?", (entity.entity_type, entity.entity_id)).fetchone()
        tags = dict(entity.tags); attributes = dict(entity.attributes); first_seen = entity.first_seen; last_seen = entity.last_seen
        if row is not None:
            existing_last_seen = float(row["last_seen"]); existing_tags = json.loads(row["tags_json"])
            if entity.last_seen >= existing_last_seen: existing_tags.update(tags)
            else:
                for key, value in tags.items(): existing_tags.setdefault(key, value)
            tags = existing_tags; existing_attributes = json.loads(row["attributes_json"])
            if entity.last_seen >= existing_last_seen: existing_attributes.update(attributes)
            attributes = existing_attributes; first_seen = min(first_seen, float(row["first_seen"])); last_seen = max(last_seen, existing_last_seen)
        self._connection.execute("INSERT OR REPLACE INTO entities(entity_type, entity_id, first_seen, last_seen, tags_json, attributes_json) VALUES (?, ?, ?, ?, ?, ?)", (entity.entity_type, entity.entity_id, first_seen, last_seen, json.dumps(tags, sort_keys=True, separators=(",", ":")), json.dumps(attributes, sort_keys=True, separators=(",", ":"))))

    def query_entities(self, *, entity_type: str | None = None, seen_after: float | None = None, limit: int = 100) -> list[EntitySnapshot]:
        if not 1 <= limit <= 5000: raise ValueError("limit must be between 1 and 5000")
        clauses: list[str] = []; params: list[object] = []
        if entity_type is not None:
            normalized = entity_type.strip().lower()
            if normalized not in {"host", "service", "container"}: raise ValueError("entity_type must be host, service, or container")
            clauses.append("entity_type = ?"); params.append(normalized)
        if seen_after is not None: clauses.append("last_seen >= ?"); params.append(seen_after)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""; params.append(limit)
        with self._lock:
            rows = self._connection.execute("SELECT entity_type, entity_id, first_seen, last_seen, tags_json, attributes_json " + f"FROM entities{where} ORDER BY last_seen DESC, entity_type, entity_id LIMIT ?", params).fetchall()
        return [EntitySnapshot(entity_type=row["entity_type"], entity_id=row["entity_id"], first_seen=float(row["first_seen"]), last_seen=float(row["last_seen"]), tags=json.loads(row["tags_json"]), attributes=json.loads(row["attributes_json"])) for row in rows]

    def overview(self) -> dict[str, object]:
        with self._lock:
            total_row = self._connection.execute("SELECT COUNT(*) AS count, MAX(timestamp) AS latest FROM telemetry_records").fetchone()
            kind_rows = self._connection.execute("SELECT kind, COUNT(*) AS count FROM telemetry_records GROUP BY kind").fetchall()
            entity_rows = self._connection.execute("SELECT entity_type, COUNT(*) AS count FROM entities GROUP BY entity_type").fetchall()
        return {"total_records": int(total_row["count"]), "latest_timestamp": float(total_row["latest"]) if total_row["latest"] is not None else None, "records_by_kind": {row["kind"]: int(row["count"]) for row in kind_rows}, "entities_by_type": {row["entity_type"]: int(row["count"]) for row in entity_rows}}

    def count(self) -> int:
        with self._lock: row = self._connection.execute("SELECT COUNT(*) AS count FROM telemetry_records").fetchone()
        return int(row["count"])

    @staticmethod
    def _normalize_tag_filters(tags: dict[str, str] | None) -> dict[str, str]:
        if not tags: return {}
        if len(tags) > 20: raise ValueError("at most 20 tag filters are allowed")
        normalized: dict[str, str] = {}
        for key, value in tags.items():
            key = key.strip(); value = value.strip()
            if not key or len(key) > 200 or not value or len(value) > 500: raise ValueError("tag filters require non-empty bounded keys and values")
            normalized[key] = value
        return normalized

    def query(self, *, kind: str | None = None, service: str | None = None, host: str | None = None, name: str | None = None, tags: dict[str, str] | None = None, start: float | None = None, end: float | None = None, limit: int = 100, before_id: int | None = None) -> list[StoredTelemetryRecord]:
        if not 1 <= limit <= 5000: raise ValueError("limit must be between 1 and 5000")
        clauses: list[str] = []; params: list[object] = []
        for column, value in (("kind", kind), ("service", service), ("host", host), ("name", name)):
            if value is not None: clauses.append(f"{column} = ?"); params.append(value)
        for key, value in self._normalize_tag_filters(tags).items():
            clauses.append("json_extract(tags_json, ?) = ?"); params.extend((f'$."{key.replace(chr(34), chr(34) * 2)}"', value))
        if start is not None: clauses.append("timestamp >= ?"); params.append(start)
        if end is not None: clauses.append("timestamp <= ?"); params.append(end)
        if before_id is not None: clauses.append("id < ?"); params.append(before_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""; params.append(limit)
        with self._lock:
            rows = self._connection.execute("SELECT id, timestamp, kind, name, service, host, tags_json, payload_json " + f"FROM telemetry_records{where} ORDER BY id DESC LIMIT ?", params).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _consumer_name(consumer: str) -> str:
        name = consumer.strip()
        if not name or len(name) > 200: raise ValueError("consumer must contain 1 to 200 characters")
        return name

    def delivery_cursor(self, consumer: str) -> int:
        name = self._consumer_name(consumer)
        with self._lock: row = self._connection.execute("SELECT last_id FROM delivery_cursors WHERE consumer = ?", (name,)).fetchone()
        return int(row["last_id"]) if row is not None else 0

    def ack_delivery(self, consumer: str, last_id: int) -> None:
        name = self._consumer_name(consumer)
        if last_id < 0: raise ValueError("last_id must not be negative")
        with self._lock, self._connection:
            self._connection.execute("INSERT INTO delivery_cursors(consumer, last_id) VALUES (?, ?) ON CONFLICT(consumer) DO UPDATE SET last_id = MAX(delivery_cursors.last_id, excluded.last_id)", (name, last_id))

    def query_after_id(self, after_id: int, *, limit: int = 500) -> list[StoredTelemetryRecord]:
        if after_id < 0: raise ValueError("after_id must not be negative")
        if not 1 <= limit <= 1000: raise ValueError("limit must be between 1 and 1000")
        with self._lock: rows = self._connection.execute("SELECT id, timestamp, kind, name, service, host, tags_json, payload_json FROM telemetry_records WHERE id > ? ORDER BY id ASC LIMIT ?", (after_id, limit)).fetchall()
        return [self._decode(row) for row in rows]

    def prune_older_than(self, timestamp: float) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM telemetry_records WHERE timestamp < ?", (timestamp,))
            return int(cursor.rowcount)

    @staticmethod
    def _decode(row: sqlite3.Row) -> StoredTelemetryRecord:
        return StoredTelemetryRecord(id=int(row["id"]), record=TelemetryRecord(kind=row["kind"], name=row["name"], payload=json.loads(row["payload_json"]), timestamp=float(row["timestamp"]), service=row["service"], host=row["host"], tags=json.loads(row["tags_json"])))
