from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

_ALLOWED_KINDS = frozenset({"metric", "log", "trace", "event", "service_check"})


def _utc_now() -> float:
    return datetime.now(tz=timezone.utc).timestamp()


def normalize_tags(tags: Mapping[str, object] | None) -> dict[str, str]:
    if not tags:
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in tags.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError("tag keys must not be empty")
        if len(key) > 200:
            raise ValueError("tag keys must be at most 200 characters")
        value = str(raw_value).strip()
        if len(value) > 500:
            raise ValueError("tag values must be at most 500 characters")
        normalized[key] = value
    if len(normalized) > 128:
        raise ValueError("a telemetry record may contain at most 128 tags")
    return dict(sorted(normalized.items()))


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    kind: str
    name: str
    payload: Mapping[str, Any]
    timestamp: float = field(default_factory=_utc_now)
    service: str | None = None
    host: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = self.kind.strip().lower()
        if kind not in _ALLOWED_KINDS:
            raise ValueError(f"unsupported telemetry kind: {self.kind!r}")
        name = self.name.strip()
        if not name or len(name) > 300:
            raise ValueError("name must contain 1 to 300 characters")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be an object")
        service = self.service.strip() if self.service else None
        host = self.host.strip() if self.host else None
        if service is not None and len(service) > 300:
            raise ValueError("service must be at most 300 characters")
        if host is not None and len(host) > 300:
            raise ValueError("host must be at most 300 characters")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "service", service)
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "tags", normalize_tags(self.tags))
        object.__setattr__(self, "payload", dict(self.payload))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TelemetryRecord":
        if not isinstance(data, Mapping):
            raise ValueError("telemetry record must be an object")
        payload = data.get("payload", {})
        tags = data.get("tags", {})
        return cls(
            kind=str(data.get("kind", "")),
            name=str(data.get("name", "")),
            payload=payload,
            timestamp=float(data.get("timestamp", _utc_now())),
            service=str(data["service"]) if data.get("service") is not None else None,
            host=str(data["host"]) if data.get("host") is not None else None,
            tags=tags,
        )
