from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .model import TelemetryRecord
from .storage import SQLiteTelemetryStore


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: int
    first_id: int | None
    last_id: int | None


class TelemetryIngestor:
    def __init__(self, store: SQLiteTelemetryStore, *, max_batch_size: int = 1000) -> None:
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")
        self.store = store
        self.max_batch_size = max_batch_size
        self._lock = threading.Lock()
        self._accepted = 0
        self._rejected = 0

    def ingest(self, raw_records: Iterable[Mapping[str, Any]]) -> IngestResult:
        batch = list(raw_records)
        if not batch:
            raise ValueError("records must not be empty")
        if len(batch) > self.max_batch_size:
            with self._lock:
                self._rejected += len(batch)
            raise ValueError(f"batch exceeds max size of {self.max_batch_size}")
        try:
            records = [TelemetryRecord.from_dict(item) for item in batch]
        except (TypeError, ValueError):
            with self._lock:
                self._rejected += len(batch)
            raise
        ids = self.store.append_many(records)
        with self._lock:
            self._accepted += len(ids)
        return IngestResult(
            accepted=len(ids),
            first_id=ids[0] if ids else None,
            last_id=ids[-1] if ids else None,
        )

    def stats(self) -> dict[str, int]:
        with self._lock:
            accepted = self._accepted
            rejected = self._rejected
        return {
            "accepted": accepted,
            "rejected": rejected,
            "stored": self.store.count(),
        }
