from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .entity import EntitySnapshot
from .ingest import TelemetryIngestor
from .storage import SQLiteTelemetryStore, StoredTelemetryRecord

_MAX_REQUEST_BYTES = 4 * 1024 * 1024


def _stored_to_dict(item: StoredTelemetryRecord) -> dict[str, Any]:
    record = item.record
    return {
        "id": item.id,
        "timestamp": record.timestamp,
        "kind": record.kind,
        "name": record.name,
        "service": record.service,
        "host": record.host,
        "tags": dict(record.tags),
        "payload": dict(record.payload),
    }


def _entity_to_dict(item: EntitySnapshot) -> dict[str, Any]:
    return {
        "type": item.entity_type,
        "id": item.entity_id,
        "first_seen": item.first_seen,
        "last_seen": item.last_seen,
        "tags": dict(item.tags),
        "attributes": dict(item.attributes),
    }


class TelemetryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], store: SQLiteTelemetryStore) -> None:
        super().__init__(server_address, TelemetryRequestHandler)
        self.store = store
        self.ingestor = TelemetryIngestor(store)


class TelemetryRequestHandler(BaseHTTPRequestHandler):
    server: TelemetryHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        target = urlsplit(self.path)
        if target.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", **self.server.ingestor.stats()})
            return
        if target.path == "/v1/query":
            try:
                self._handle_query(parse_qs(target.query))
            except (TypeError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if target.path == "/v1/entities":
            try:
                self._handle_entities(parse_qs(target.query))
            except (TypeError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/v1/telemetry":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
            return
        if length <= 0 or length > _MAX_REQUEST_BYTES:
            self._json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                if length > _MAX_REQUEST_BYTES
                else HTTPStatus.BAD_REQUEST,
                {"error": "request body must contain 1 to 4194304 bytes"},
            )
            return
        try:
            body = json.loads(self.rfile.read(length))
            records = body.get("records") if isinstance(body, dict) else None
            if not isinstance(records, list):
                raise ValueError("body must be an object containing a records array")
            result = self.server.ingestor.ingest(records)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(
            HTTPStatus.ACCEPTED,
            {
                "accepted": result.accepted,
                "first_id": result.first_id,
                "last_id": result.last_id,
            },
        )

    @staticmethod
    def _one(params: dict[str, list[str]], name: str) -> str | None:
        values = params.get(name)
        return values[-1] if values else None

    def _handle_query(self, params: dict[str, list[str]]) -> None:
        def one(name: str) -> str | None:
            return self._one(params, name)

        records = self.server.store.query(
            kind=one("kind"),
            service=one("service"),
            host=one("host"),
            name=one("name"),
            start=float(one("start")) if one("start") is not None else None,
            end=float(one("end")) if one("end") is not None else None,
            limit=int(one("limit") or "100"),
            before_id=int(one("before_id")) if one("before_id") is not None else None,
        )
        self._json(HTTPStatus.OK, {"records": [_stored_to_dict(item) for item in records]})

    def _handle_entities(self, params: dict[str, list[str]]) -> None:
        def one(name: str) -> str | None:
            return self._one(params, name)

        entities = self.server.store.query_entities(
            entity_type=one("type"),
            seen_after=float(one("seen_after")) if one("seen_after") is not None else None,
            limit=int(one("limit") or "100"),
        )
        self._json(HTTPStatus.OK, {"entities": [_entity_to_dict(item) for item in entities]})

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def build_server(host: str, port: int, store: SQLiteTelemetryStore) -> TelemetryHTTPServer:
    return TelemetryHTTPServer((host, port), store)
