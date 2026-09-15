from __future__ import annotations

import hmac
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .entity import EntitySnapshot
from .ingest import TelemetryIngestor
from .storage import SQLiteTelemetryStore, StoredTelemetryRecord
from .web_ui import dashboard_html

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

    def __init__(
        self,
        server_address: tuple[str, int],
        store: SQLiteTelemetryStore,
        *,
        auth_token: str | None = None,
    ) -> None:
        if auth_token is not None and not auth_token:
            raise ValueError("auth_token must not be empty")
        super().__init__(server_address, TelemetryRequestHandler)
        self.store = store
        self.ingestor = TelemetryIngestor(store)
        self.auth_token = auth_token


class TelemetryRequestHandler(BaseHTTPRequestHandler):
    server: TelemetryHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        target = urlsplit(self.path)
        if target.path in {"/", "/ui"}:
            self._html(HTTPStatus.OK, dashboard_html())
            return
        if target.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", **self.server.ingestor.stats()})
            return
        if target.path in {"/v1/query", "/v1/entities", "/v1/overview"}:
            if not self._authorized():
                self._unauthorized()
                return
        try:
            if target.path == "/v1/query":
                self._handle_query(parse_qs(target.query))
                return
            if target.path == "/v1/entities":
                self._handle_entities(parse_qs(target.query))
                return
            if target.path == "/v1/overview":
                self._json(HTTPStatus.OK, self.server.store.overview())
                return
        except (TypeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/v1/telemetry":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            self._unauthorized()
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

    def _authorized(self) -> bool:
        token = self.server.auth_token
        if token is None:
            return True
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return hmac.compare_digest(header[len(prefix) :], token)

    def _unauthorized(self) -> None:
        self._json(
            HTTPStatus.UNAUTHORIZED,
            {"error": "authentication required"},
            extra_headers={"WWW-Authenticate": "Bearer"},
        )

    def _html(self, status: HTTPStatus, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)


def build_server(
    host: str,
    port: int,
    store: SQLiteTelemetryStore,
    *,
    auth_token: str | None = None,
) -> TelemetryHTTPServer:
    return TelemetryHTTPServer((host, port), store, auth_token=auth_token)
