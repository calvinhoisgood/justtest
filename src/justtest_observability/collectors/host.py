from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from ..model import TelemetryRecord


@dataclass(frozen=True, slots=True)
class HostSnapshot:
    logical_cpu_count: int
    memory_total_bytes: int | None = None
    memory_available_bytes: int | None = None
    uptime_seconds: float | None = None
    load_1: float | None = None
    load_5: float | None = None
    load_15: float | None = None


def _linux_snapshot() -> HostSnapshot:
    meminfo = _parse_linux_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
    uptime_text = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
    load = os.getloadavg()
    return HostSnapshot(
        logical_cpu_count=os.cpu_count() or 1,
        memory_total_bytes=meminfo.get("MemTotal"),
        memory_available_bytes=meminfo.get("MemAvailable"),
        uptime_seconds=float(uptime_text),
        load_1=float(load[0]),
        load_5=float(load[1]),
        load_15=float(load[2]),
    )


def _parse_linux_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        pieces = raw.strip().split()
        if not pieces:
            continue
        value = int(pieces[0])
        unit = pieces[1].lower() if len(pieces) > 1 else ""
        if unit == "kb":
            value *= 1024
        values[key] = value
    return values


def _windows_snapshot() -> HostSnapshot:
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    uptime_ms = ctypes.windll.kernel32.GetTickCount64()
    return HostSnapshot(
        logical_cpu_count=os.cpu_count() or 1,
        memory_total_bytes=int(status.ullTotalPhys),
        memory_available_bytes=int(status.ullAvailPhys),
        uptime_seconds=float(uptime_ms) / 1000.0,
    )


def read_host_snapshot() -> HostSnapshot:
    if sys.platform.startswith("linux"):
        return _linux_snapshot()
    if sys.platform == "win32":
        return _windows_snapshot()
    load: tuple[float, float, float] | None = None
    try:
        load = tuple(float(value) for value in os.getloadavg())
    except (AttributeError, OSError):
        pass
    return HostSnapshot(
        logical_cpu_count=os.cpu_count() or 1,
        load_1=load[0] if load else None,
        load_5=load[1] if load else None,
        load_15=load[2] if load else None,
    )


class HostCollector:
    name = "host"

    def __init__(self, snapshot_reader: Callable[[], HostSnapshot] = read_host_snapshot) -> None:
        self._snapshot_reader = snapshot_reader

    def collect(self) -> list[TelemetryRecord]:
        snapshot = self._snapshot_reader()
        values: Mapping[str, float | int | None] = {
            "system.cpu.logical_count": snapshot.logical_cpu_count,
            "system.memory.total_bytes": snapshot.memory_total_bytes,
            "system.memory.available_bytes": snapshot.memory_available_bytes,
            "system.uptime.seconds": snapshot.uptime_seconds,
            "system.load.1": snapshot.load_1,
            "system.load.5": snapshot.load_5,
            "system.load.15": snapshot.load_15,
        }
        if snapshot.memory_total_bytes is not None and snapshot.memory_available_bytes is not None:
            values = dict(values)
            values["system.memory.used_bytes"] = max(
                snapshot.memory_total_bytes - snapshot.memory_available_bytes, 0
            )
        return [
            TelemetryRecord(
                kind="metric",
                name=name,
                payload={"value": value, "metric_type": "gauge"},
            )
            for name, value in values.items()
            if value is not None
        ]
