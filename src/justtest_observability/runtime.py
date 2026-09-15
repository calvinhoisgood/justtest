from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Iterable, Protocol

from .model import TelemetryRecord
from .resource import ResourceContext
from .storage import SQLiteTelemetryStore


class Collector(Protocol):
    name: str

    def collect(self) -> Iterable[TelemetryRecord]: ...


@dataclass(frozen=True, slots=True)
class CollectorStatus:
    cycles: int
    records: int
    errors: int
    last_error: str | None


class CollectorRuntime:
    """Runs collectors with per-collector failure isolation and shared enrichment."""

    def __init__(
        self,
        store: SQLiteTelemetryStore,
        collectors: Iterable[Collector],
        *,
        resource: ResourceContext | None = None,
    ) -> None:
        self.store = store
        self.collectors = list(collectors)
        if not self.collectors:
            raise ValueError("at least one collector is required")
        names = [collector.name for collector in self.collectors]
        if any(not name.strip() for name in names) or len(set(names)) != len(names):
            raise ValueError("collector names must be non-empty and unique")
        self.resource = resource or ResourceContext.local()
        self._lock = threading.Lock()
        self._status = {
            name: {"cycles": 0, "records": 0, "errors": 0, "last_error": None}
            for name in names
        }

    def collect_once(self) -> int:
        persisted = 0
        for collector in self.collectors:
            try:
                records = [self.resource.enrich(record) for record in collector.collect()]
                self.store.append_many(records)
                persisted += len(records)
                with self._lock:
                    status = self._status[collector.name]
                    status["cycles"] += 1
                    status["records"] += len(records)
                    status["last_error"] = None
            except Exception as exc:  # collector boundaries deliberately isolate failures
                with self._lock:
                    status = self._status[collector.name]
                    status["cycles"] += 1
                    status["errors"] += 1
                    status["last_error"] = f"{type(exc).__name__}: {exc}"
        return persisted

    def snapshot(self) -> dict[str, CollectorStatus]:
        with self._lock:
            return {
                name: CollectorStatus(
                    cycles=int(values["cycles"]),
                    records=int(values["records"]),
                    errors=int(values["errors"]),
                    last_error=values["last_error"],
                )
                for name, values in self._status.items()
            }

    def run_forever(self, *, interval: float = 15.0, stop_event: threading.Event | None = None) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        stop = stop_event or threading.Event()
        while not stop.is_set():
            started = time.monotonic()
            self.collect_once()
            delay = max(interval - (time.monotonic() - started), 0.0)
            stop.wait(delay)
