from __future__ import annotations

import platform
import socket
from dataclasses import dataclass, field
from typing import Mapping

from .model import TelemetryRecord, normalize_tags


@dataclass(frozen=True, slots=True)
class ResourceContext:
    host: str = field(default_factory=socket.gethostname)
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        host = self.host.strip()
        if not host:
            raise ValueError("resource host must not be empty")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "tags", normalize_tags(self.tags))

    @classmethod
    def local(cls, tags: Mapping[str, str] | None = None) -> "ResourceContext":
        defaults = {
            "os": platform.system().lower() or "unknown",
            "arch": platform.machine().lower() or "unknown",
        }
        defaults.update(tags or {})
        return cls(tags=defaults)

    def enrich(self, record: TelemetryRecord) -> TelemetryRecord:
        tags = dict(self.tags)
        tags.update(record.tags)
        return TelemetryRecord(
            kind=record.kind,
            name=record.name,
            payload=record.payload,
            timestamp=record.timestamp,
            service=record.service,
            host=record.host or self.host,
            tags=tags,
        )
