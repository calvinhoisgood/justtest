from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen

from .storage import SQLiteTelemetryStore, StoredTelemetryRecord


def _record_dict(item: StoredTelemetryRecord) -> dict[str, object]:
    record = item.record
    return {
        "kind": record.kind,
        "name": record.name,
        "timestamp": record.timestamp,
        "service": record.service,
        "host": record.host,
        "tags": dict(record.tags),
        "payload": dict(record.payload),
    }


def _encode_batch(
    rows: list[StoredTelemetryRecord], *, max_body_bytes: int
) -> tuple[bytes, list[StoredTelemetryRecord]]:
    prefix = b'{"records":['
    suffix = b"]}"
    encoded: list[bytes] = []
    selected: list[StoredTelemetryRecord] = []
    size = len(prefix) + len(suffix)
    for row in rows:
        item = json.dumps(
            _record_dict(row),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        additional = len(item) + (1 if encoded else 0)
        if size + additional > max_body_bytes:
            if not encoded:
                raise ValueError(
                    f"telemetry record {row.id} exceeds forwarding body limit of {max_body_bytes} bytes"
                )
            break
        encoded.append(item)
        selected.append(row)
        size += additional
    return prefix + b",".join(encoded) + suffix, selected


@dataclass(frozen=True, slots=True)
class ForwarderStatus:
    attempts: int
    delivered_batches: int
    delivered_records: int
    errors: int
    last_acked_id: int
    last_error: str | None


class DurableHTTPForwarder:
    """At-least-once ordered forwarding backed by a durable SQLite consumer cursor."""

    def __init__(
        self,
        store: SQLiteTelemetryStore,
        endpoint: str,
        *,
        consumer: str = "default-http",
        batch_size: int = 500,
        timeout: float = 5.0,
        max_body_bytes: int = 3_500_000,
        bearer_token: str | None = None,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("endpoint must use http:// or https://")
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 1024 <= max_body_bytes <= 4 * 1024 * 1024:
            raise ValueError("max_body_bytes must be between 1024 and 4194304")
        if bearer_token is not None and not bearer_token:
            raise ValueError("bearer_token must not be empty")
        self.store = store
        self.endpoint = endpoint
        self.store.delivery_cursor(consumer)
        self.consumer = consumer.strip()
        self.batch_size = batch_size
        self.timeout = timeout
        self.max_body_bytes = max_body_bytes
        self.bearer_token = bearer_token
        self._opener = opener
        self._lock = threading.Lock()
        self._status = {
            "attempts": 0,
            "delivered_batches": 0,
            "delivered_records": 0,
            "errors": 0,
            "last_acked_id": self.store.delivery_cursor(self.consumer),
            "last_error": None,
        }

    def snapshot(self) -> ForwarderStatus:
        with self._lock:
            return ForwarderStatus(
                attempts=int(self._status["attempts"]),
                delivered_batches=int(self._status["delivered_batches"]),
                delivered_records=int(self._status["delivered_records"]),
                errors=int(self._status["errors"]),
                last_acked_id=int(self._status["last_acked_id"]),
                last_error=self._status["last_error"],
            )

    def forward_once(self) -> int:
        cursor = self.store.delivery_cursor(self.consumer)
        rows = self.store.query_after_id(cursor, limit=self.batch_size)
        if not rows:
            return 0
        body, selected = _encode_batch(rows, max_body_bytes=self.max_body_bytes)
        if not selected:
            return 0
        headers = {"Content-Type": "application/json"}
        if self.bearer_token is not None:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        request = Request(
            self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        with self._lock:
            self._status["attempts"] += 1
        try:
            response = self._opener(request, timeout=self.timeout)
            try:
                status_value = getattr(response, "status", None)
                if status_value is None:
                    status_value = response.getcode()
                status = int(status_value)
                response.read()
            finally:
                response.close()
            if not 200 <= status < 300:
                raise RuntimeError(f"forwarding endpoint returned HTTP {status}")
        except Exception as exc:
            with self._lock:
                self._status["errors"] += 1
                self._status["last_error"] = f"{type(exc).__name__}: {exc}"
            raise

        last_id = selected[-1].id
        self.store.ack_delivery(self.consumer, last_id)
        with self._lock:
            self._status["delivered_batches"] += 1
            self._status["delivered_records"] += len(selected)
            self._status["last_acked_id"] = last_id
            self._status["last_error"] = None
        return len(selected)

    def run_forever(
        self,
        *,
        interval: float = 2.0,
        stop_event: threading.Event | None = None,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        stop = stop_event or threading.Event()
        while not stop.is_set():
            try:
                delivered = self.forward_once()
            except Exception:
                delivered = 0
            stop.wait(0.0 if delivered >= self.batch_size else interval)
