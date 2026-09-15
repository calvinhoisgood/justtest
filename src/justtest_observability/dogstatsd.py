from __future__ import annotations

import re
import socket
import threading
from dataclasses import dataclass
from typing import Iterable

from .model import TelemetryRecord
from .resource import ResourceContext
from .storage import SQLiteTelemetryStore

_METRIC_NAME = re.compile(r"^[A-Za-z0-9_.]+$")
_METRIC_TYPES = {
    "c": "count",
    "g": "gauge",
    "ms": "timer",
    "h": "histogram",
    "s": "set",
    "d": "distribution",
}
_SERVICE_CHECK_STATUS = {0: "ok", 1: "warning", 2: "critical", 3: "unknown"}
_CARDINALITIES = frozenset({"none", "low", "orchestrator", "high"})


class DogStatsDParseError(ValueError):
    pass


def _service_from_tags(tags: dict[str, str]) -> str | None:
    return tags.get("service") or tags.get("service_name") or None


def _parse_tags(raw: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    if not raw:
        return tags
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        key, separator, value = item.partition(":")
        key = key.strip()
        if not key:
            raise DogStatsDParseError("tag key must not be empty")
        tags[key] = value.strip() if separator else ""
    return tags


def _parse_timestamp(value: str) -> float:
    try:
        timestamp = float(value)
    except ValueError as exc:
        raise DogStatsDParseError("timestamp must be numeric") from exc
    if timestamp <= 0:
        raise DogStatsDParseError("timestamp must be positive")
    return timestamp


def _metric_records(message: bytes) -> list[TelemetryRecord]:
    try:
        text = message.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DogStatsDParseError("DogStatsD messages must be UTF-8") from exc
    parts = text.split("|")
    if len(parts) < 2:
        raise DogStatsDParseError("metric is missing its type")
    name_and_values = parts[0]
    name, separator, raw_values = name_and_values.partition(":")
    if not separator or not raw_values:
        raise DogStatsDParseError("metric must use name:value syntax")
    if not _METRIC_NAME.fullmatch(name):
        raise DogStatsDParseError("metric name contains unsupported characters")
    metric_type = _METRIC_TYPES.get(parts[1])
    if metric_type is None:
        raise DogStatsDParseError(f"unsupported metric type: {parts[1]!r}")

    sample_rate = 1.0
    tags: dict[str, str] = {}
    container_id: str | None = None
    cardinality: str | None = None
    extensions: list[str] = []
    for field in parts[2:]:
        if field.startswith("@"):
            try:
                sample_rate = float(field[1:])
            except ValueError as exc:
                raise DogStatsDParseError("sample rate must be numeric") from exc
            if not 0 <= sample_rate <= 1:
                raise DogStatsDParseError("sample rate must be between 0 and 1")
        elif field.startswith("#"):
            tags.update(_parse_tags(field[1:]))
        elif field.startswith("c:"):
            container_id = field[2:].strip() or None
        elif field.startswith("card:"):
            cardinality = field[5:].strip().lower()
            if cardinality not in _CARDINALITIES:
                raise DogStatsDParseError(f"unsupported cardinality: {cardinality!r}")
        elif field:
            extensions.append(field)

    values = raw_values.split(":")
    if metric_type == "set" and len(values) != 1:
        raise DogStatsDParseError("set metrics do not support value packing")

    records: list[TelemetryRecord] = []
    for raw_value in values:
        if raw_value == "":
            raise DogStatsDParseError("metric value must not be empty")
        if metric_type == "set":
            value: str | float = raw_value
        else:
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise DogStatsDParseError("metric values must be numeric") from exc
        payload: dict[str, object] = {
            "value": value,
            "metric_type": metric_type,
            "sample_rate": sample_rate,
            "source": "dogstatsd",
        }
        if container_id is not None:
            payload["origin_container_id"] = container_id
        if cardinality is not None:
            payload["cardinality"] = cardinality
        if extensions:
            payload["extensions"] = list(extensions)
        records.append(
            TelemetryRecord(
                kind="metric",
                name=name,
                service=_service_from_tags(tags),
                tags=tags,
                payload=payload,
            )
        )
    return records


def _event_record(message: bytes) -> TelemetryRecord:
    header_end = message.find(b"}:")
    if header_end < 3:
        raise DogStatsDParseError("invalid event header")
    try:
        lengths = message[3:header_end].decode("ascii")
        title_length_text, text_length_text = lengths.split(",", 1)
        title_length = int(title_length_text)
        text_length = int(text_length_text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise DogStatsDParseError("invalid event lengths") from exc
    if title_length <= 0 or text_length < 0:
        raise DogStatsDParseError("event lengths must be non-negative and title must not be empty")

    cursor = header_end + 2
    title_bytes = message[cursor : cursor + title_length]
    if len(title_bytes) != title_length:
        raise DogStatsDParseError("event title is shorter than declared")
    cursor += title_length
    if message[cursor : cursor + 1] != b"|":
        raise DogStatsDParseError("event title length does not match payload")
    cursor += 1
    text_bytes = message[cursor : cursor + text_length]
    if len(text_bytes) != text_length:
        raise DogStatsDParseError("event text is shorter than declared")
    cursor += text_length
    try:
        title = title_bytes.decode("utf-8")
        event_text = text_bytes.decode("utf-8").replace("\\n", "\n")
        tail = message[cursor:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DogStatsDParseError("DogStatsD messages must be UTF-8") from exc
    if tail and not tail.startswith("|"):
        raise DogStatsDParseError("event metadata must be pipe-delimited")

    timestamp: float | None = None
    host: str | None = None
    tags: dict[str, str] = {}
    payload: dict[str, object] = {"text": event_text, "source": "dogstatsd"}
    extensions: list[str] = []
    for field in tail[1:].split("|") if tail else []:
        if field.startswith("d:"):
            timestamp = _parse_timestamp(field[2:])
        elif field.startswith("h:"):
            host = field[2:].strip() or None
        elif field.startswith("k:"):
            payload["aggregation_key"] = field[2:]
        elif field.startswith("p:"):
            payload["priority"] = field[2:]
        elif field.startswith("s:"):
            payload["source_type_name"] = field[2:]
        elif field.startswith("t:"):
            payload["alert_type"] = field[2:]
        elif field.startswith("#"):
            tags.update(_parse_tags(field[1:]))
        elif field:
            extensions.append(field)
    if extensions:
        payload["extensions"] = extensions

    kwargs: dict[str, object] = {}
    if timestamp is not None:
        kwargs["timestamp"] = timestamp
    return TelemetryRecord(
        kind="event",
        name=title,
        service=_service_from_tags(tags),
        host=host,
        tags=tags,
        payload=payload,
        **kwargs,
    )


def _service_check_record(message: bytes) -> TelemetryRecord:
    try:
        text = message.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DogStatsDParseError("DogStatsD messages must be UTF-8") from exc
    parts = text.split("|")
    if len(parts) < 3 or parts[0] != "_sc":
        raise DogStatsDParseError("invalid service check")
    name = parts[1].strip()
    if not name:
        raise DogStatsDParseError("service check name must not be empty")
    try:
        status = int(parts[2])
    except ValueError as exc:
        raise DogStatsDParseError("service check status must be an integer") from exc
    if status not in _SERVICE_CHECK_STATUS:
        raise DogStatsDParseError("service check status must be between 0 and 3")

    timestamp: float | None = None
    host: str | None = None
    tags: dict[str, str] = {}
    payload: dict[str, object] = {
        "status": status,
        "status_name": _SERVICE_CHECK_STATUS[status],
        "source": "dogstatsd",
    }
    extensions: list[str] = []
    for field in parts[3:]:
        if field.startswith("d:"):
            timestamp = _parse_timestamp(field[2:])
        elif field.startswith("h:"):
            host = field[2:].strip() or None
        elif field.startswith("#"):
            tags.update(_parse_tags(field[1:]))
        elif field.startswith("m:"):
            payload["message"] = field[2:]
        elif field:
            extensions.append(field)
    if extensions:
        payload["extensions"] = extensions

    kwargs: dict[str, object] = {}
    if timestamp is not None:
        kwargs["timestamp"] = timestamp
    return TelemetryRecord(
        kind="service_check",
        name=name,
        service=_service_from_tags(tags),
        host=host,
        tags=tags,
        payload=payload,
        **kwargs,
    )


def parse_message(message: bytes | str) -> list[TelemetryRecord]:
    raw = message.encode("utf-8") if isinstance(message, str) else bytes(message)
    raw = raw.strip(b"\r\n")
    if not raw:
        return []
    if raw.startswith(b"_e{"):
        return [_event_record(raw)]
    if raw.startswith(b"_sc|"):
        return [_service_check_record(raw)]
    return _metric_records(raw)


def iter_datagram_messages(datagram: bytes) -> Iterable[bytes]:
    for line in datagram.splitlines():
        line = line.strip()
        if line:
            yield line


@dataclass(frozen=True, slots=True)
class DogStatsDStatus:
    datagrams: int
    messages: int
    records: int
    errors: int
    bytes_received: int
    last_error: str | None


class DogStatsDServer:
    """Dependency-free, loopback-friendly DogStatsD UDP ingestion server."""

    def __init__(
        self,
        store: SQLiteTelemetryStore,
        *,
        host: str = "127.0.0.1",
        port: int = 8125,
        resource: ResourceContext | None = None,
        max_datagram_bytes: int = 65507,
    ) -> None:
        if not host:
            raise ValueError("host must not be empty")
        if not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if not 512 <= max_datagram_bytes <= 65507:
            raise ValueError("max_datagram_bytes must be between 512 and 65507")
        self.store = store
        self.host = host
        self.port = port
        self.resource = resource or ResourceContext.local()
        self.max_datagram_bytes = max_datagram_bytes
        self._lock = threading.Lock()
        self._status = {
            "datagrams": 0,
            "messages": 0,
            "records": 0,
            "errors": 0,
            "bytes_received": 0,
            "last_error": None,
        }
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._address: tuple[str, int] | None = None

    @property
    def address(self) -> tuple[str, int]:
        if self._address is None:
            raise RuntimeError("server has not been started")
        return self._address

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("server is already started")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.host, self.port))
            sock.settimeout(0.2)
        except Exception:
            sock.close()
            raise
        bound_host, bound_port = sock.getsockname()[:2]
        self._socket = sock
        self._address = (str(bound_host), int(bound_port))
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dogstatsd", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        sock = self._socket
        if sock is not None:
            sock.close()
        thread.join(timeout=2.0)
        self._thread = None
        self._socket = None

    def snapshot(self) -> DogStatsDStatus:
        with self._lock:
            return DogStatsDStatus(
                datagrams=int(self._status["datagrams"]),
                messages=int(self._status["messages"]),
                records=int(self._status["records"]),
                errors=int(self._status["errors"]),
                bytes_received=int(self._status["bytes_received"]),
                last_error=self._status["last_error"],
            )

    def _record_error(self, exc: Exception) -> None:
        with self._lock:
            self._status["errors"] += 1
            self._status["last_error"] = f"{type(exc).__name__}: {exc}"

    def _run(self) -> None:
        while not self._stop.is_set():
            sock = self._socket
            if sock is None:
                return
            try:
                datagram, _peer = sock.recvfrom(self.max_datagram_bytes + 1)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                self._record_error(RuntimeError("DogStatsD socket receive failed"))
                continue
            with self._lock:
                self._status["datagrams"] += 1
                self._status["bytes_received"] += len(datagram)
            if len(datagram) > self.max_datagram_bytes:
                self._record_error(DogStatsDParseError("datagram exceeds configured size limit"))
                continue
            for message in iter_datagram_messages(datagram):
                with self._lock:
                    self._status["messages"] += 1
                try:
                    records = [self.resource.enrich(record) for record in parse_message(message)]
                    self.store.append_many(records)
                except Exception as exc:
                    self._record_error(exc)
                    continue
                with self._lock:
                    self._status["records"] += len(records)
                    self._status["last_error"] = None
