from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .model import TelemetryRecord

_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StoredTelemetryRecord:
    id: int
    record: TelemetryRecord


class SQLiteTelemetryStore:
    """Durable local telemetry store with bounded query primitives."""

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
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_records (
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
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry_records(timestamp DESC, id DESC)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_kind_time ON telemetry_records(kind, timestamp DESC)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_service_time ON telemetry_records(service, timestamp DESC)"
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )

    def append_many(self, records: Iterable[TelemetryRecord]) -> list[int]:
        rows = list(records)
        if not rows:
            return []
        ids: list[int] = []
        with self._lock, self._connection:
            for record in rows:
                cursor = self._connection.execute(
                    """
                    INSERT INTO telemetry_records(
                        timestamp, kind, name, service, host, tags_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.timestamp,
                        record.kind,
                        record.name,
                        record.service,
                        record.host,
                        json.dumps(record.tags, sort_keys=True, separators=(",", ":")),
                        json.dumps(record.payload, sort_keys=True, separators=(",", ":")),
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS count FROM telemetry_records").fetchone()
        return int(row["count"])

    def query(
        self,
        *,
        kind: str | None = None,
        service: str | None = None,
        host: str | None = None,
        name: str | None = None,
        start: float | None = None,
        end: float | None = None,
        limit: int = 100,
        before_id: int | None = None,
    ) -> list[StoredTelemetryRecord]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be between 1 and 5000")
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (("kind", kind), ("service", service), ("host", host), ("name", name)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end)
        if before_id is not None:
            clauses.append("id < ?")
            params.append(before_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT id, timestamp, kind, name, service, host, tags_json, payload_json "
            f"FROM telemetry_records{where} ORDER BY id DESC LIMIT ?"
        )
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [self._decode(row) for row in rows]

    def prune_older_than(self, timestamp: float) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM telemetry_records WHERE timestamp < ?", (timestamp,)
            )
            return int(cursor.rowcount)

    @staticmethod
    def _decode(row: sqlite3.Row) -> StoredTelemetryRecord:
        return StoredTelemetryRecord(
            id=int(row["id"]),
            record=TelemetryRecord(
                kind=row["kind"],
                name=row["name"],
                payload=json.loads(row["payload_json"]),
                timestamp=float(row["timestamp"]),
                service=row["service"],
                host=row["host"],
                tags=json.loads(row["tags_json"]),
            ),
        )
