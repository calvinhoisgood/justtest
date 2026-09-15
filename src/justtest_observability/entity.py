from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .model import TelemetryRecord

_ENTITY_TAG_KEYS = frozenset(
    {
        "env",
        "version",
        "team",
        "region",
        "zone",
        "availability_zone",
        "cluster",
        "namespace",
        "os",
        "arch",
    }
)


@dataclass(frozen=True, slots=True)
class EntitySnapshot:
    entity_type: str
    entity_id: str
    first_seen: float
    last_seen: float
    tags: Mapping[str, str]
    attributes: Mapping[str, object]


def _entity_tags(record: TelemetryRecord) -> dict[str, str]:
    return {key: value for key, value in record.tags.items() if key in _ENTITY_TAG_KEYS}


def derive_entities(record: TelemetryRecord) -> list[EntitySnapshot]:
    tags = _entity_tags(record)
    entities: list[EntitySnapshot] = []
    if record.host:
        entities.append(
            EntitySnapshot(
                entity_type="host",
                entity_id=record.host,
                first_seen=record.timestamp,
                last_seen=record.timestamp,
                tags=tags,
                attributes={"hostname": record.host},
            )
        )
    if record.service:
        entities.append(
            EntitySnapshot(
                entity_type="service",
                entity_id=record.service,
                first_seen=record.timestamp,
                last_seen=record.timestamp,
                tags=tags,
                attributes={"service": record.service},
            )
        )
    raw_container_id = record.payload.get("origin_container_id")
    if raw_container_id is not None:
        container_id = str(raw_container_id).strip()
        if container_id:
            attributes: dict[str, object] = {"container_id": container_id}
            cardinality = record.payload.get("cardinality")
            if cardinality is not None:
                attributes["cardinality"] = str(cardinality)
            entities.append(
                EntitySnapshot(
                    entity_type="container",
                    entity_id=container_id,
                    first_seen=record.timestamp,
                    last_seen=record.timestamp,
                    tags=tags,
                    attributes=attributes,
                )
            )
    return entities
