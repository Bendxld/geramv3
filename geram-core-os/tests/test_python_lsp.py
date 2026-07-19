import asyncio
import json
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.python_lsp import _handle, _sanitize_diagnostics, _sanitize_result
from app.core.python_lsp import (
    PYRIGHT_VERSION,
    PythonLspError,
    PythonLspManager,
    _relative_from_uri,
    _trusted_pyright,
    _workspace_uri,
)
from app.core.workspace import WorkspaceService


class PythonLspSecurityTests(unittest.TestCase):
    def test_pyright_is_exact_locked_mit_dependency(self):
        root = Path(__file__).resolve().parents[1]
        package = json.loads((root / "electron/package.json").read_text(encoding="utf-8"))
        lock = json.loads((root / "electron/package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(package["devDependencies"]["pyright"], PYRIGHT_VERSION)
        locked = lock["packages"]["node_modules/pyright"]
        self.assertEqual(locked["version"], PYRIGHT_VERSION)
        self.assertRegex(locked["integrity"], r"^sha512-")
        self.assertEqual(locked["license"], "MIT")
        node, pyright = _trusted_pyright()
        self.assertEqual(node, Path("/usr/bin/node"))
        self.assertEqual(pyright.name, "pyright")
        self.assertTrue((root / "electron/licenses/PYRIGHT-LICENSE.txt").is_file())

    def test_workspace_uri_mapping_rejects_external_and_traversal(self):
        self.assertEqual(_workspace_uri("pkg/main.py"), "file:///workspace/pkg/main.py")
        self.assertEqual(_relative_from_uri("file:///workspace/pkg/main.py"), "pkg/main.py")
        for uri in ("file:///etc/passwd", "file:///workspace/../secret.py", "https://example.invalid/a.py"):
            self.assertIsNone(_relative_from_uri(uri))

    def test_results_and_diagnostics_do_not_expose_external_uris_or_links(self):
        value = [
            {"uri": "file:///workspace/main.py", "range": {}},
            {"uri": "file:///usr/lib/python/typeshed.pyi", "range": {}},
        ]
        self.assertEqual(_sanitize_result(value), [{"uri": "file:///workspace/main.py", "range": {}}])
        diagnostics = _sanitize_diagnostics([{
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
            "message": "bad", "severity": 1, "source": "x",
            "codeDescription": {"href": "https://example.invalid"},
        }])
        self.assertNotIn("codeDescription", diagnostics[0])
        self.assertEqual(diagnostics[0]["source"], "Pyright")


class PythonLspManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "lib.py").write_text(
            "def double(value: int) -> int:\n    return value * 2\n", encoding="utf-8"
        )
        self.main_text = "from lib import double\n\nresult = double('bad')\ndouble(2)\n"
        (self.root / "main.py").write_text(self.main_text, encoding="utf-8")
        self.manager = PythonLspManager(WorkspaceService(self.root))

    async def asyncTearDown(self):
        await self.manager.stop()
        self.temporary.cleanup()

    async def _open(self):
        await self.manager.start()
        await self.manager.notify("textDocument/didOpen", {"textDocument": {
            "uri": _workspace_uri("main.py"), "languageId": "python",
            "version": 1, "text": self.main_text,
        }})

    async def test_real_pyright_initialization_features_imports_and_diagnostics(self):
        events = []

        async def subscriber(payload):
            events.append(payload)

        self.manager.subscribe(subscriber)
        await self._open()
        for _ in range(80):
            if any(event.get("type") == "diagnostics" and event.get("diagnostics") for event in events):
                break
            await asyncio.sleep(0.05)
        position = {"line": 2, "character": 10}
        document = {"textDocument": {"uri": _workspace_uri("main.py")}, "position": position}
        completion = await self.manager.request("textDocument/completion", {
            "textDocument": {"uri": _workspace_uri("main.py")},
            "position": {"line": 2, "character": 3}, "context": {"triggerKind": 1},
        })
        hover = await self.manager.request("textDocument/hover", document)
        definition = await self.manager.request("textDocument/definition", document)
        references = await self.manager.request("textDocument/references", {**document, "context": {"includeDeclaration": True}})
        rename = await self.manager.request("textDocument/rename", {**document, "newName": "twice"})
        symbols = await self.manager.request("textDocument/documentSymbol", {"textDocument": {"uri": _workspace_uri("lib.py")}})
        workspace_symbols = await self.manager.request("workspace/symbol", {"query": "double"})
        signature = await self.manager.request("textDocument/signatureHelp", {
            "textDocument": {"uri": _workspace_uri("main.py")},
            "position": {"line": 3, "character": 8},
        })
        self.assertTrue(completion)
        self.assertTrue(hover)
        self.assertEqual(definition[0]["uri"], _workspace_uri("lib.py"))
        self.assertGreaterEqual(len(references), 3)
        self.assertTrue(rename.get("changes") or rename.get("documentChanges"))
        self.assertEqual(symbols[0]["name"], "double")
        self.assertTrue(workspace_symbols)
        self.assertTrue(signature and signature.get("signatures"))
        diagnostic = next(event for event in events if event.get("diagnostics"))
        self.assertEqual(diagnostic["path"], "main.py")
        self.assertIn("cannot be assigned", diagnostic["diagnostics"][0]["message"])
        self.assertTrue(self.manager.running)
        process_ids = [self.manager.process.pid]
        for process_id in process_ids:
            children_file = Path("/proc", str(process_id), "task", str(process_id), "children")
            if children_file.is_file():
                process_ids.extend(int(value) for value in children_file.read_text().split())
        commands = b" ".join(
            Path("/proc", str(process_id), "cmdline").read_bytes().replace(b"\0", b" ")
            for process_id in process_ids if Path("/proc", str(process_id), "cmdline").is_file()
        )
        self.assertIn(b"/opt/pyright/langserver.index.js --stdio", commands)
        self.assertNotIn(self.main_text.encode("utf-8"), commands)
        host_network = os.readlink("/proc/self/ns/net")
        self.assertTrue(any(
            os.readlink(f"/proc/{process_id}/ns/net") != host_network
            for process_id in process_ids if Path("/proc", str(process_id), "ns/net").exists()
        ))

    async def test_change_clears_type_diagnostic_and_cleanup_removes_process(self):
        events = []

        async def subscriber(payload): events.append(payload)

        self.manager.subscribe(subscriber)
        await self._open()
        for _ in range(160):
            if any(
                event.get("path") == "main.py" and event.get("diagnostics")
                for event in events
            ):
                break
            await asyncio.sleep(0.05)
        self.assertTrue(any(
            event.get("path") == "main.py" and event.get("diagnostics")
            for event in events
        ))
        corrected = self.main_text.replace("'bad'", "1")
        await self.manager.notify("textDocument/didChange", {
            "textDocument": {"uri": _workspace_uri("main.py"), "version": 2},
            "contentChanges": [{"text": corrected}],
        })
        for _ in range(80):
            matching = [event for event in events if event.get("path") == "main.py"]
            if matching and matching[-1].get("diagnostics") == []:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(matching[-1]["diagnostics"], [])
        pid = self.manager.process.pid
        await self.manager.stop()
        self.assertFalse(Path("/proc", str(pid)).exists())

    async def test_crash_is_detected_and_next_start_is_controlled(self):
        await self.manager.start()
        first_pid = self.manager.process.pid
        os.killpg(first_pid, signal.SIGKILL)
        await self.manager.process.wait()
        for _ in range(40):
            if not self.manager.running:
                break
            await asyncio.sleep(0.05)
        await self.manager.start()
        self.assertTrue(self.manager.running)
        self.assertNotEqual(self.manager.process.pid, first_pid)

    async def test_paths_server_absence_and_timeouts_fail_closed(self):
        outside = Path(self.temporary.name).parent / "outside.py"
        outside.write_text("", encoding="utf-8")
        (self.root / "external.py").symlink_to(outside)
        try:
            for path in ("../outside.py", str(outside), "external.py", "main.js", ".git/config.py", "node_modules/a.py"):
                with self.subTest(path=path), self.assertRaises(PythonLspError):
                    self.manager.validate_python_path(path)
            with patch("app.core.python_lsp._PYRIGHT_ENTRYPOINT", self.root / "missing.js"):
                with self.assertRaises(PythonLspError):
                    await self.manager.start()
            await self.manager.start()
            with patch.object(self.manager, "_send", new=AsyncMock()):
                with self.assertRaises(PythonLspError) as caught:
                    await self.manager.request("test/never", {}, timeout=0.01)
                self.assertEqual(caught.exception.code, "python_lsp_timeout")
        finally:
            outside.unlink(missing_ok=True)


class PythonLspBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_allows_only_bounded_lifecycle_and_lsp_methods(self):
        manager = MagicMock()
        manager.notify = AsyncMock()
        manager.request = AsyncMock()
        manager.validate_python_path.side_effect = lambda value: value if value == "main.py" else (_ for _ in ()).throw(PythonLspError("invalid_python_path"))
        manager.validate_text.side_effect = lambda value: value
        opened = set()
        await _handle(manager, {"type": "open", "path": "main.py", "version": 1, "text": "x = 1\n"}, opened)
        self.assertEqual(opened, {"main.py"})
        manager.notify.assert_awaited()
        manager.request.return_value = {"contents": "int"}
        response = await _handle(manager, {
            "type": "request", "request_id": "one", "method": "textDocument/hover",
            "path": "main.py", "position": {"line": 0, "character": 0},
        }, opened)
        self.assertEqual(response["request_id"], "one")
        for message in (
            {"type": "request", "request_id": "x", "method": "workspace/executeCommand"},
            {"type": "request", "request_id": "x", "method": "textDocument/rename", "path": "main.py", "position": {"line": 0, "character": 0}, "new_name": "bad-name"},
        ):
            with self.assertRaises(PythonLspError):
                await _handle(manager, message, opened)


if __name__ == "__main__":
    unittest.main()
