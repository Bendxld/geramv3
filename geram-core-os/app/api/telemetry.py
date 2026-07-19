"""
Telemetry Router — GERAM CORE OS

Provides a point-in-time snapshot of system resources (CPU/RAM) via psutil.
This REST endpoint acts as a fallback / initial-state fetch for the HUD;
the live/continuous stream is intended to run over the WebSocket channel
(/ws/hud) in a follow-up implementation pass, reusing get_snapshot() below.
"""

import threading
import time

import psutil
from fastapi import APIRouter

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

_network_lock = threading.Lock()
_network_previous = psutil.net_io_counters()
_network_previous_at = time.monotonic()


def _network_kbs() -> float:
    global _network_previous, _network_previous_at
    with _network_lock:
        now = time.monotonic()
        current = psutil.net_io_counters()
        elapsed = max(now - _network_previous_at, 0.001)
        transferred = (
            current.bytes_sent + current.bytes_recv
            - _network_previous.bytes_sent - _network_previous.bytes_recv
        )
        _network_previous = current
        _network_previous_at = now
    return round(max(0.0, transferred / 1024 / elapsed), 1)


def _temperature_celsius() -> float | None:
    try:
        temperatures = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    preferred = ("coretemp", "k10temp", "cpu_thermal", "acpitz")
    groups = [temperatures.get(name, []) for name in preferred]
    groups.extend(value for key, value in temperatures.items() if key not in preferred)
    for readings in groups:
        for reading in readings:
            if isinstance(reading.current, (int, float)):
                return round(float(reading.current), 1)
    return None


def _power_percent(cpu_percent: float, ram_percent: float) -> float:
    try:
        battery = psutil.sensors_battery()
    except (AttributeError, OSError):
        battery = None
    if battery is not None:
        return round(float(battery.percent), 1)
    return round(max(0.0, 100.0 - ((cpu_percent + ram_percent) / 2.0)), 1)


def get_snapshot() -> dict:
    """Reusable snapshot function — also intended for WebSocket broadcast loop."""
    cpu = float(psutil.cpu_percent(interval=None))
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": cpu,
        "ram_percent": float(memory.percent),
        "ram_used_mb": round(memory.used / (1024 * 1024), 2),
        "ram_total_mb": round(memory.total / (1024 * 1024), 2),
        "network_kbs": _network_kbs(),
        "temperature_c": _temperature_celsius(),
        "disk_percent": float(disk.percent),
        "power_percent": _power_percent(cpu, float(memory.percent)),
        "system_uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
    }


@router.get("/snapshot")
async def telemetry_snapshot():
    return get_snapshot()
