"""Strict WebSocket bridge from Monaco to the local Pyright manager."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.workspace import workspace_service
from app.core.config import settings
from app.core.python_lsp import PythonLspError, PythonLspManager, _relative_from_uri, _workspace_uri

router = APIRouter(tags=["python-lsp"])
python_lsp_manager = PythonLspManager(workspace_service)
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w{0,127}$")
_REQUEST_METHODS = frozenset({
    "textDocument/completion", "textDocument/hover", "textDocument/signatureHelp",
    "textDocument/definition", "textDocument/references", "textDocument/rename",
    "textDocument/documentSymbol", "workspace/symbol",
})


def _local_websocket(websocket: WebSocket) -> bool:
    host = websocket.client.host if websocket.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return False
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    allowed = {
        f"http://127.0.0.1:{settings.APP_PORT}",
        f"http://localhost:{settings.APP_PORT}",
    }
    return origin in allowed


def _position(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise PythonLspError("invalid_python_position")
    line, character = value.get("line"), value.get("character")
    if isinstance(line, bool) or isinstance(character, bool):
        raise PythonLspError("invalid_python_position")
    if not isinstance(line, int) or not isinstance(character, int) or not 0 <= line <= 1_000_000 or not 0 <= character <= 1_000_000:
        raise PythonLspError("invalid_python_position")
    return {"line": line, "character": character}


def _sanitize_result(value: Any) -> Any:
    if isinstance(value, list):
        return [item for raw in value if (item := _sanitize_result(raw)) is not None]
    if not isinstance(value, dict):
        return value
    sanitized = {}
    for key, raw in value.items():
        if key in {"uri", "targetUri"}:
            relative = _relative_from_uri(raw)
            if relative is None:
                return None
            sanitized[key] = _workspace_uri(relative)
        elif key == "changes" and isinstance(raw, dict):
            changes = {}
            for uri, edits in raw.items():
                relative = _relative_from_uri(uri)
                if relative is not None:
                    changes[_workspace_uri(relative)] = _sanitize_result(edits)
            sanitized[key] = changes
        else:
            sanitized[key] = _sanitize_result(raw)
    return sanitized


def _sanitize_diagnostics(value: object) -> list[dict[str, Any]]:
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("range"), dict):
            continue
        severity = item.get("severity")
        if severity not in {1, 2, 3, 4}:
            severity = 1
        result.append({
            "range": item["range"],
            "message": str(item.get("message") or "Python diagnostic")[:8192],
            "severity": severity,
            "code": item.get("code") if isinstance(item.get("code"), (str, int)) else None,
            "source": "Pyright",
        })
    return result


async def _handle(manager: PythonLspManager, message: object, opened: set[str]) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("type") not in {"open", "change", "save", "close", "request"}:
        raise PythonLspError("invalid_python_lsp_message")
    message_type = message["type"]
    if message_type in {"open", "change", "save", "close"}:
        path = manager.validate_python_path(message.get("path"))
        uri = _workspace_uri(path)
        if message_type == "open":
            text = manager.validate_text(message.get("text"))
            version = message.get("version", 1)
            if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 2_147_483_647:
                raise PythonLspError("invalid_python_document")
            await manager.notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": "python", "version": version, "text": text,
            }})
            opened.add(path)
        elif message_type == "change":
            if path not in opened:
                raise PythonLspError("python_document_not_open")
            text = manager.validate_text(message.get("text"))
            version = message.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise PythonLspError("invalid_python_document")
            await manager.notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}],
            })
        elif message_type == "save":
            if path not in opened:
                raise PythonLspError("python_document_not_open")
            text = manager.validate_text(message.get("text"))
            await manager.notify("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text})
        else:
            if path in opened:
                await manager.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
                opened.discard(path)
        return None

    request_id = message.get("request_id")
    method = message.get("method")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id) or method not in _REQUEST_METHODS:
        raise PythonLspError("invalid_python_lsp_request")
    if method == "workspace/symbol":
        query = message.get("query", "")
        if not isinstance(query, str) or len(query) > 128:
            raise PythonLspError("invalid_python_lsp_request")
        params = {"query": query}
    else:
        path = manager.validate_python_path(message.get("path"))
        params = {"textDocument": {"uri": _workspace_uri(path)}}
        if method not in {"textDocument/documentSymbol"}:
            params["position"] = _position(message.get("position"))
        if method == "textDocument/completion":
            params["context"] = {"triggerKind": 1}
        elif method == "textDocument/references":
            params["context"] = {"includeDeclaration": True}
        elif method == "textDocument/rename":
            new_name = message.get("new_name")
            if not isinstance(new_name, str) or not _IDENTIFIER.fullmatch(new_name):
                raise PythonLspError("invalid_python_rename")
            params["newName"] = new_name
    result = await manager.request(method, params)
    return {"type": "response", "request_id": request_id, "result": _sanitize_result(result)}


@router.websocket("/ws/python-lsp")
async def python_lsp_socket(websocket: WebSocket) -> None:
    if not _local_websocket(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    manager = python_lsp_manager
    opened: set[str] = set()

    async def send(payload: dict[str, Any]) -> None:
        if payload.get("type") == "diagnostics":
            payload = dict(payload)
            payload["diagnostics"] = _sanitize_diagnostics(payload.get("diagnostics"))
        await websocket.send_json(payload)

    manager.subscribe(send)
    try:
        await manager.start()
        await websocket.send_json({"type": "status", "status": "ready", "server": "pyright", "version": "1.1.411"})
        while True:
            message = await websocket.receive_json()
            try:
                response = await _handle(manager, message, opened)
                if response is not None:
                    await websocket.send_json(response)
            except PythonLspError as error:
                request_id = message.get("request_id") if isinstance(message, dict) else None
                await websocket.send_json({"type": "error", "request_id": request_id, "code": error.code})
    except WebSocketDisconnect:
        pass
    except PythonLspError as error:
        await websocket.send_json({"type": "status", "status": "unavailable", "code": error.code})
    finally:
        for path in tuple(opened):
            try:
                await manager.notify("textDocument/didClose", {"textDocument": {"uri": _workspace_uri(path)}})
            except PythonLspError:
                break
        manager.unsubscribe(send)
