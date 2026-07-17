"""
HUD WebSocket — GERAM CORE OS

Single bidirectional channel for the HUD: broadcasts a telemetry snapshot
every TELEMETRY_INTERVAL_SECONDS (reusing app/api/telemetry.py::get_snapshot,
same source the /telemetry/snapshot REST fallback uses) and accepts
inbound messages from the HUD.

Inbound message handling is intentionally a placeholder for now — ARES
task events / HUD-originated commands are a follow-up pass (see
app/main.py roadmap comments).
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.api.telemetry import get_snapshot

logger = logging.getLogger("geram_core")

router = APIRouter(tags=["websocket"])

connected_clients: set[WebSocket] = set()


async def broadcast_telemetry(payload: dict) -> None:
    """Sends payload as JSON to every currently connected client.

    Dead/broken connections are dropped from the registry instead of
    letting one bad client take down the whole broadcast loop.
    """
    muertos = []
    for cliente in connected_clients:
        try:
            await cliente.send_json(payload)
        except Exception:
            muertos.append(cliente)

    for cliente in muertos:
        connected_clients.discard(cliente)


async def telemetry_broadcast_loop() -> None:
    """Runs forever (launched as an asyncio task on app startup)."""
    while True:
        await broadcast_telemetry({"type": "telemetry", "data": get_snapshot()})
        await asyncio.sleep(settings.TELEMETRY_INTERVAL_SECONDS)


@router.websocket("/ws/hud")
async def hud_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            # TODO(next pass): manejar comandos reales del HUD (ARES task
            # events, controles) — por ahora solo se drena el mensaje para
            # mantener la conexión viva y detectar el disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)
