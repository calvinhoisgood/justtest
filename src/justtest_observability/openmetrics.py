from __future__ import annotations

import math
import re
from typing import Mapping
from urllib.request import Request, urlopen

from .model import TelemetryRecord, normalize_tags

_METRIC_NAME = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]*$")
_LABEL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TYPE_NAMES = frozenset({"counter", "gauge", "histogram", "summary", "untyped"})
_CONTENT_TYPES = frozenset({"text/plain", "application/openmetrics-text"})


class OpenMetricsParseError(ValueError):
    pass


def _unescape_label(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            result.append(char)
            index += 1
            continue
        index += 1
        if index >= len(value):
            raise OpenMetricsParseError("label value ends with an incomplete escape")
        escaped = value[index]
        if escaped == "n":
            result.append("\n")
        elif escaped in {'\\', '"'}:
            result.append(escaped)
        else:
            raise OpenMetricsParseError(f"unsupported label escape: \\{escaped}")
        index += 1
    return "".join(result)


def _parse_labels(text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        match = _LABEL_NAME.match(text, index)
        if match is None:
            raise OpenMetricsParseError("invalid label name")
        name = match.group(0)
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != "=":
            raise OpenMetricsParseError('label must use name="value" syntax')
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != '"':
            raise OpenMetricsParseError("label value must be quoted")
        index += 1
        raw: list[str] = []
        while index < len(text):
            char = text[index]
            if char == '"':
                index += 1
                break
            if char == "\\":
                if index + 1 >= len(text):
                    raise OpenMetricsParseError("label value ends with an incomplete escape")
                raw.extend((char, text[index + 1]))
                index += 2
                continue
            raw.append(char)
            index += 1
        else:
            raise OpenMetricsParseError("unterminated label value")
        labels[name] = _unescape_label("".join(raw))
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            break
        if text[index] != ",":
            raise OpenMetricsParseError("labels must be comma separated")
        index += 1
        if index == len(text):
            break
    return labels


def _split_sample(line: str) -> tuple[str, dict[str, str], str, str | None]:
    index = 0
    while index < len(line) and not line[index].isspace() and line[index] != "{":
        index += 1
    name = line[:index]
    if not _METRIC_NAME.fullmatch(name):
        raise OpenMetricsParseError(f"unsupported metric name: {name!r}")
    labels: dict[str, str] = {}
    if index < len(line) and line[index] == "{":
        index += 1
        start = index
        in_quotes = False
        escaped = False
        while index < len(line):
            char = line[index]
            if escaped:
                escaped = False
            elif char == "\\" and in_quotes:
                escaped = True
            elif char == '"':
                in_quotes = not in_quotes
            elif char == "}" and not in_quotes:
                break
            index += 1
        if index >= len(line) or line[index] != "}":
            raise OpenMetricsParseError("unterminated label set")
        labels = _parse_labels(line[start:index])
        index += 1
    rest = line[index:].strip().split()
    if len(rest) not in {1, 2}:
        raise OpenMetricsParseError("sample must contain value and optional timestamp")
    return name, labels, rest[0], rest[1] if len(rest) == 2 else None


def _metric_type(name: str, declared: Mapping[str, str]) -> str:
    if name in declared:
        return declared[name]
    for suffix in ("_bucket", "_sum", "_count"):
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            if declared.get(base) in {"histogram", "summary"}:
                return declared[base]
    return "untyped"


def parse_exposition(
    text: str,
    *,
    common_tags: Mapping[str, str] | None = None,
    max_samples: int = 10_000,
) -> list[TelemetryRecord]:
    if max_samples < 1:
        raise ValueError("max_samples must be positive")
    target_tags = normalize_tags(common_tags)
    declared: dict[str, str] = {}
    records: list[TelemetryRecord] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line == "# EOF":
            continue
        if line.startswith("#"):
            parts = line.split(None, 3)
            if len(parts) >= 2 and parts[1] == "TYPE":
                if len(parts) != 4:
                    raise OpenMetricsParseError(f"line {line_number}: malformed TYPE directive")
                name, metric_type = parts[2], parts[3].strip().lower()
                if not _METRIC_NAME.fullmatch(name) or metric_type not in _TYPE_NAMES:
                    raise OpenMetricsParseError(f"line {line_number}: unsupported TYPE directive")
                if name in declared:
                    raise OpenMetricsParseError(f"line {line_number}: duplicate TYPE directive")
                declared[name] = metric_type
            continue
        if len(records) >= max_samples:
            raise OpenMetricsParseError(f"exposition exceeds max sample count of {max_samples}")
        try:
            name, labels, raw_value, raw_timestamp = _split_sample(line)
            value = float(raw_value)
        except ValueError as exc:
            raise OpenMetricsParseError(f"line {line_number}: invalid numeric value") from exc
        except OpenMetricsParseError as exc:
            raise OpenMetricsParseError(f"line {line_number}: {exc}") from exc
        if not math.isfinite(value):
            raise OpenMetricsParseError(
                f"line {line_number}: non-finite values are not supported by local JSON storage"
            )
        tags = dict(target_tags)
        tags.update(labels)
        payload: dict[str, object] = {
            "value": value,
            "metric_type": _metric_type(name, declared),
            "source": "openmetrics",
        }
        kwargs: dict[str, object] = {}
        if raw_timestamp is not None:
            try:
                timestamp_ms = int(raw_timestamp)
            except ValueError as exc:
                raise OpenMetricsParseError(
                    f"line {line_number}: timestamp must be integer milliseconds"
                ) from exc
            if timestamp_ms <= 0:
                raise OpenMetricsParseError(f"line {line_number}: timestamp must be positive")
            kwargs["timestamp"] = timestamp_ms / 1000.0
        records.append(
            TelemetryRecord(
                kind="metric",
                name=name,
                service=tags.get("service") or tags.get("service_name") or None,
                tags=tags,
                payload=payload,
                **kwargs,
            )
        )
    return records


class OpenMetricsCollector:
    """Bounded HTTP scraper for the common Prometheus/OpenMetrics text subset."""

    def __init__(
        self,
        url: str,
        *,
        name: str = "openmetrics",
        tags: Mapping[str, str] | None = None,
        timeout: float = 5.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_samples: int = 10_000,
        opener=urlopen,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValueError("OpenMetrics URL must use http:// or https://")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("collector name must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 1024 <= max_response_bytes <= 16 * 1024 * 1024:
            raise ValueError("max_response_bytes must be between 1024 and 16777216")
        if not 1 <= max_samples <= 100_000:
            raise ValueError("max_samples must be between 1 and 100000")
        self.url = url
        self.name = normalized_name
        self.tags = normalize_tags(tags)
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.max_samples = max_samples
        self._opener = opener

    def collect(self) -> list[TelemetryRecord]:
        request = Request(
            self.url,
            headers={
                "Accept": (
                    "application/openmetrics-text;version=1.0.0,"
                    "text/plain;version=0.0.4;q=0.9"
                ),
                "Accept-Encoding": "identity",
                "User-Agent": "justtest-observability/0.1",
            },
        )
        response = self._opener(request, timeout=self.timeout)
        try:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > self.max_response_bytes:
                raise ValueError("OpenMetrics response exceeds configured size limit")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type and content_type not in _CONTENT_TYPES:
                raise ValueError(f"unsupported OpenMetrics Content-Type: {content_type}")
            body = response.read(self.max_response_bytes + 1)
        finally:
            response.close()
        if len(body) > self.max_response_bytes:
            raise ValueError("OpenMetrics response exceeds configured size limit")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("OpenMetrics response must be UTF-8") from exc
        return parse_exposition(text, common_tags=self.tags, max_samples=self.max_samples)
