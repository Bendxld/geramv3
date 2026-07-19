"""
HUD WebSocket — GERAM CORE OS

Single bidirectional channel for the HUD: broadcasts a telemetry snapshot
every TELEMETRY_INTERVAL_SECONDS (reusing app/api/telemetry.py::get_snapshot,
same source the /telemetry/snapshot REST fallback uses) and accepts a small,
closed set of local HUD controls.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.runtime_state import runtime_state_store
from app.api.telemetry import get_snapshot

logger = logging.getLogger("geram_core")

router = APIRouter(tags=["websocket"])

connected_clients: set[WebSocket] = set()
MAX_HUD_MESSAGE_BYTES = 4096


def _local_websocket(websocket: WebSocket) -> bool:
    """Apply the same loopback and browser-Origin boundary as local APIs."""
    host = websocket.client.host if websocket.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return False
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    return origin in {
        f"http://127.0.0.1:{settings.APP_PORT}",
        f"http://localhost:{settings.APP_PORT}",
    }


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


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json({"type": "error", "error": {"code": code, "message": message}})


async def handle_hud_message(websocket: WebSocket, raw_message: str) -> None:
    """Handle only bounded, explicitly supported HUD messages.

    Runtime switches use the same per-OS-user store as the REST API, so a
    downloaded installation retains its own user's state. No shell command or
    arbitrary agent action can be submitted through this channel.
    """
    if len(raw_message.encode("utf-8")) > MAX_HUD_MESSAGE_BYTES:
        await _send_error(websocket, "message_too_large", "HUD message exceeds the limit")
        return
    try:
        payload = json.loads(raw_message)
    except (json.JSONDecodeError, UnicodeError):
        await _send_error(websocket, "invalid_json", "HUD message must be valid JSON")
        return
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        await _send_error(websocket, "invalid_message", "HUD message requires a type")
        return

    message_type = payload["type"]
    if message_type == "ping":
        await websocket.send_json({"type": "pong"})
        return
    if message_type == "get_telemetry":
        await websocket.send_json({"type": "telemetry", "data": get_snapshot()})
        return
    if message_type == "get_runtime_state":
        await websocket.send_json(
            {"type": "runtime_state", "data": runtime_state_store.load().model_dump(mode="json")}
        )
        return
    if message_type == "set_runtime_state":
        data = payload.get("data")
        allowed = {"voice_enabled", "vision_enabled", "offline_forced"}
        if (
            not isinstance(data, dict)
            or not data
            or set(data) - allowed
            or any(type(value) is not bool for value in data.values())
        ):
            await _send_error(
                websocket,
                "invalid_runtime_state",
                "Runtime state accepts only boolean voice, vision, and offline fields",
            )
            return
        try:
            updated = runtime_state_store.update(data)
        except OSError:
            await _send_error(websocket, "runtime_state_unavailable", "Runtime state could not be saved")
            return
        await websocket.send_json(
            {"type": "runtime_state", "data": updated.model_dump(mode="json")}
        )
        return

    await _send_error(websocket, "unsupported_message", "Unsupported HUD message type")


@router.websocket("/ws/hud")
async def hud_websocket(websocket: WebSocket) -> None:
    if not _local_websocket(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await handle_hud_message(websocket, await websocket.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)
