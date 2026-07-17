"""
Telemetry Router — GERAM CORE OS

Provides a point-in-time snapshot of system resources (CPU/RAM) via psutil.
This REST endpoint acts as a fallback / initial-state fetch for the HUD;
the live/continuous stream is intended to run over the WebSocket channel
(/ws/hud) in a follow-up implementation pass, reusing get_snapshot() below.
"""

import psutil
from fastapi import APIRouter

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def get_snapshot() -> dict:
    """Reusable snapshot function — also intended for WebSocket broadcast loop."""
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_used_mb": round(psutil.virtual_memory().used / (1024 * 1024), 2),
        "ram_total_mb": round(psutil.virtual_memory().total / (1024 * 1024), 2),
    }


@router.get("/snapshot")
async def telemetry_snapshot():
    return get_snapshot()
