"""Controlled local Pyright process and bounded JSON-RPC transport."""
from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable

from app.core.sandbox_backend import (
    SandboxUnavailableError,
    build_sandbox_prefix,
    detect_sandbox_backend,
)
from app.core.workspace import MAX_FILE_BYTES, WorkspaceError, WorkspaceService

MAX_LSP_MESSAGE_BYTES = 8 * 1024 * 1024
LSP_REQUEST_TIMEOUT = 8.0
PYRIGHT_VERSION = "1.1.411"
_ROOT = Path(__file__).resolve().parents[2]
_PYRIGHT_PACKAGE = _ROOT / "electron" / "node_modules" / "pyright"
_PYRIGHT_ENTRYPOINT = _PYRIGHT_PACKAGE / "langserver.index.js"
_NODE = Path("/usr/bin/node")
_EXCLUDES = [
    "**/.git", "**/.hg", "**/.svn", "**/.venv", "**/venv", "**/__pycache__",
    "**/node_modules", "**/dist", "**/build", "**/.env", "**/.env.*",
]


class PythonLspError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _trusted_pyright() -> tuple[Path, Path]:
    try:
        node_modules = _PYRIGHT_PACKAGE.parent.resolve(strict=True)
        package = _PYRIGHT_PACKAGE.resolve(strict=True)
        entrypoint = _PYRIGHT_ENTRYPOINT.resolve(strict=True)
        node = _NODE.resolve(strict=True)
        metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        raise PythonLspError("python_lsp_unavailable") from None
    if package.parent != node_modules or entrypoint.parent != package or metadata.get("name") != "pyright" or metadata.get("version") != PYRIGHT_VERSION:
        raise PythonLspError("python_lsp_unavailable")
    if not node.is_file() or not os.access(node, os.X_OK):
        raise PythonLspError("python_lsp_unavailable")
    return node, package


def _workspace_uri(path: str = "") -> str:
    suffix = "/" + path if path else ""
    return "file:///workspace" + suffix


def _relative_from_uri(uri: object) -> str | None:
    prefix = "file:///workspace/"
    if not isinstance(uri, str) or not uri.startswith(prefix):
        return None
    relative = uri[len(prefix):]
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts or "\\" in relative:
        return None
    return path.as_posix()


class PythonLspManager:
    def __init__(self, workspace: WorkspaceService):
        self.workspace = workspace
        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task | None = None
        self.stderr_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._subscribers: set[Callable[[dict[str, Any]], Awaitable[None]]] = set()

    @property
    def running(self) -> bool:
        return bool(self.process and self.process.returncode is None and self.reader_task and not self.reader_task.done())

    def subscribe(self, callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._subscribers.discard(callback)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for callback in self._subscribers:
            try:
                await callback(payload)
            except Exception:
                dead.append(callback)
        for callback in dead:
            self._subscribers.discard(callback)

    def validate_python_path(self, path: object, *, must_exist: bool = True) -> str:
        if not isinstance(path, str) or not path.endswith(".py"):
            raise PythonLspError("invalid_python_path")
        try:
            resolved = self.workspace.resolve_path(path)
        except WorkspaceError:
            raise PythonLspError("invalid_python_path") from None
        candidate = self.workspace.root.joinpath(*resolved.parts)
        if must_exist and (not candidate.is_file() or candidate.is_symlink()):
            raise PythonLspError("invalid_python_path")
        if len(resolved.parts) > self.workspace.max_tree_depth + 1:
            raise PythonLspError("invalid_python_path")
        return PurePosixPath(*resolved.parts).as_posix()

    @staticmethod
    def validate_text(text: object) -> str:
        if not isinstance(text, str):
            raise PythonLspError("invalid_python_document")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            raise PythonLspError("invalid_python_document") from None
        if size > MAX_FILE_BYTES:
            raise PythonLspError("python_document_too_large")
        return text

    async def start(self) -> None:
        async with self._start_lock:
            if self.running:
                return
            await self._cleanup_process()
            node, package = _trusted_pyright()
            try:
                backend = detect_sandbox_backend()
                prefix = build_sandbox_prefix(backend, self.workspace.root, _ROOT)
            except SandboxUnavailableError:
                raise PythonLspError("python_lsp_sandbox_unavailable") from None
            prefix = prefix[:-1] + ["--ro-bind", str(package), "/opt/pyright", "--"]
            argv = prefix + [str(node), "/opt/pyright/langserver.index.js", "--stdio"]
            env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp/home", "NODE_ENV": "production"}
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=self.workspace.root,
                    env=env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
            except (OSError, ValueError):
                self.process = None
                raise PythonLspError("python_lsp_unavailable") from None
            self.reader_task = asyncio.create_task(self._reader_loop())
            self.stderr_task = asyncio.create_task(self._drain_stderr())
            try:
                await self.request("initialize", {
                    "processId": None,
                    "clientInfo": {"name": "GERAM CORE OS", "version": "0.1.0"},
                    "rootUri": _workspace_uri(),
                    "workspaceFolders": [{"uri": _workspace_uri(), "name": "workspace"}],
                    "capabilities": {
                        "workspace": {"configuration": True, "workspaceFolders": True},
                        "textDocument": {
                            "completion": {"completionItem": {"snippetSupport": True}},
                            "hover": {}, "signatureHelp": {}, "definition": {},
                            "references": {}, "rename": {"prepareSupport": False},
                            "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                            "publishDiagnostics": {"relatedInformation": True},
                        },
                    },
                }, timeout=12.0)
                await self.notify("initialized", {})
                await self.notify("workspace/didChangeConfiguration", {"settings": self._configuration()})
            except Exception:
                await self._cleanup_process()
                raise PythonLspError("python_lsp_unavailable") from None

    def _configuration(self) -> dict[str, Any]:
        return {
            "python": {
                "analysis": {
                    "typeCheckingMode": "basic",
                    "diagnosticMode": "workspace",
                    "autoSearchPaths": False,
                    "useLibraryCodeForTypes": False,
                    "exclude": list(_EXCLUDES),
                }
            }
        }

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin or self.process.returncode is not None:
            raise PythonLspError("python_lsp_unavailable")
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_LSP_MESSAGE_BYTES:
            raise PythonLspError("python_lsp_message_too_large")
        framed = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw
        async with self._write_lock:
            self.process.stdin.write(framed)
            try:
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                raise PythonLspError("python_lsp_unavailable") from None

    async def request(self, method: str, params: dict[str, Any], *, timeout: float = LSP_REQUEST_TIMEOUT) -> Any:
        if not self.running and method != "initialize":
            await self.start()
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            response = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            raise PythonLspError("python_lsp_timeout") from None
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            raise PythonLspError("python_lsp_request_failed")
        return response.get("result")

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if not self.running and method != "exit":
            await self.start()
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _read_message(self) -> dict[str, Any]:
        if not self.process or not self.process.stdout:
            raise EOFError
        header = await self.process.stdout.readuntil(b"\r\n\r\n")
        if len(header) > 8192:
            raise PythonLspError("python_lsp_protocol_error")
        length = None
        for line in header.decode("ascii", "strict").split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length is None or not 0 <= length <= MAX_LSP_MESSAGE_BYTES:
            raise PythonLspError("python_lsp_protocol_error")
        return json.loads((await self.process.stdout.readexactly(length)).decode("utf-8"))

    async def _reader_loop(self) -> None:
        try:
            while True:
                message = await self._read_message()
                if "id" in message and "method" not in message:
                    future = self._pending.get(message["id"])
                    if future and not future.done():
                        future.set_result(message)
                elif "id" in message and "method" in message:
                    await self._handle_server_request(message)
                elif message.get("method") == "textDocument/publishDiagnostics":
                    params = message.get("params") or {}
                    relative = _relative_from_uri(params.get("uri"))
                    if relative:
                        try:
                            relative = self.validate_python_path(relative)
                        except PythonLspError:
                            continue
                        await self._broadcast({
                            "type": "diagnostics", "path": relative,
                            "diagnostics": params.get("diagnostics") if isinstance(params.get("diagnostics"), list) else [],
                        })
        except (EOFError, asyncio.IncompleteReadError, asyncio.CancelledError, PythonLspError, ValueError, json.JSONDecodeError):
            pass
        finally:
            error = PythonLspError("python_lsp_unavailable")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            await self._broadcast({"type": "status", "status": "unavailable"})

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        result: Any = None
        if method == "workspace/configuration":
            items = (message.get("params") or {}).get("items") or []
            result = [self._configuration().get("python", {}) for _ in items]
        elif method == "workspace/workspaceFolders":
            result = [{"uri": _workspace_uri(), "name": "workspace"}]
        await self._send({"jsonrpc": "2.0", "id": message.get("id"), "result": result})

    async def _drain_stderr(self) -> None:
        if not self.process or not self.process.stderr:
            return
        while await self.process.stderr.read(4096):
            pass

    async def stop(self) -> None:
        if self.running:
            try:
                await self.request("shutdown", {}, timeout=2.0)
                await self.notify("exit", {})
            except PythonLspError:
                pass
        await self._cleanup_process()

    async def _cleanup_process(self) -> None:
        process = self.process
        reader = self.reader_task
        stderr = self.stderr_task
        self.process = None
        self.reader_task = None
        self.stderr_task = None
        current = asyncio.current_task()
        for task in (reader, stderr):
            if task and task is not current and not task.done():
                task.cancel()
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 1.0)
            except asyncio.TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
