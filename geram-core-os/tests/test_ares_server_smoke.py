"""Real HTTP smoke test for the two enabled A.R.E.S. workflows."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / "venv/bin/python"
HOST = "127.0.0.1"
BASE_CONTENT = "VALUE = 'base'\n"
PROPOSED_CONTENT = "VALUE = 'proposed'\n"
PARENT_MARKER = "synthetic-smoke-parent-secret-91c4"
VALIDATION_MARKER = "synthetic-validation-secret-4d27"
DETACHED_MARKER = "synthetic-detached-child-6f82"


def _descendants(root_pid: int) -> set[int]:
    parents: dict[int, int] = {}
    proc = Path("/proc")
    if not proc.is_dir():
        return set()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    found: set[int] = set()
    pending = [root_pid]
    while pending:
        parent = pending.pop()
        children = [pid for pid, ppid in parents.items() if ppid == parent and pid not in found]
        found.update(children)
        pending.extend(children)
    return found


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((HOST, 0))
        return int(listener.getsockname()[1])


def _pids_with_cmdline_marker(marker: str) -> set[int]:
    matches: set[int] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return matches
    encoded_marker = marker.encode("ascii")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        if encoded_marker in command:
            matches.add(int(entry.name))
    return matches


class HttpClient:
    def __init__(self, port: int):
        self.port = port
        self.base_url = f"http://{HOST}:{port}"
        self.local_origin = self.base_url

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        *,
        origin: str | None = None,
    ) -> tuple[int, object, str]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if origin is not None:
            headers["Origin"] = origin
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read().decode("utf-8", "replace")
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            status = error.code
        try:
            parsed: object = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return status, parsed, raw

    def json(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        *,
        origin: str | None = None,
        expected: int = 200,
    ) -> dict:
        status, parsed, raw = self.request(method, path, payload, origin=origin)
        if status != expected or not isinstance(parsed, dict):
            raise AssertionError(f"Unexpected local HTTP result: {status} {raw[:200]}")
        return parsed


class SmokeServer:
    def __init__(
        self,
        workspace: Path,
        data_dir: Path,
        log_dir: Path,
        *,
        disable_bwrap: bool = False,
    ):
        self.workspace = workspace
        self.port = _available_port()
        self.client = HttpClient(self.port)
        log_relative = (log_dir / "sessions.jsonl").relative_to(ROOT)
        environment = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(ROOT),
            "LANG": "C.UTF-8",
            "APP_ENV": "production",
            "APP_HOST": HOST,
            "APP_PORT": str(self.port),
            "GERAM_WORKSPACE_ROOT": str(workspace),
            "GERAM_LOCAL_DATA_DIR": str(data_dir),
            "CODEX_SESSION_LOG_PATH": log_relative.as_posix(),
            "AGENTS_AUTO_DISCOVER": "false",
            "TELEGRAM_BOT_TOKEN": "",
            "OPENAI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "GROQ_API_KEY": "",
            "GERAM_SYNTHETIC_PARENT_SECRET": PARENT_MARKER,
            "GERAM_SMOKE_DISABLE_BWRAP": "1" if disable_bwrap else "0",
        }
        self.process = subprocess.Popen(
            [str(PYTHON), str(Path(__file__).resolve()), "--serve"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.output = ""
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                status, payload, _raw = self.client.request("GET", "/health")
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
                continue
            if status == 200 and isinstance(payload, dict) and payload.get("status") == "ok":
                return
            time.sleep(0.05)
        self.stop()
        raise AssertionError(f"The local smoke server did not start: {self.output[:500]}")

    def stop(self) -> None:
        if self.process.poll() is None:
            known = _descendants(self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            for pid in known:
                if Path("/proc", str(pid)).exists():
                    raise AssertionError("A smoke server descendant survived shutdown")
        if self.process.stdout is not None:
            self.output += self.process.stdout.read()
            self.process.stdout.close()
        if Path("/proc", str(self.process.pid)).exists():
            raise AssertionError("The smoke server survived shutdown")
        if self.process.returncode not in {0, -15}:
            raise AssertionError(f"The smoke server stopped unexpectedly: {self.output[:500]}")

    def __enter__(self) -> "SmokeServer":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


class AresRealServerSmokeTests(unittest.TestCase):
    def setUp(self):
        self.workspace_temp = tempfile.TemporaryDirectory(prefix=".ares-smoke-workspace-", dir=ROOT)
        self.data_temp = tempfile.TemporaryDirectory(prefix=".ares-smoke-data-", dir=ROOT.parent)
        # Settings strips leading dots/slashes from relative log paths. Keep the
        # managed directory name identical to the effective runtime path so the
        # TemporaryDirectory cleanup cannot leave a normalized sibling behind.
        self.log_temp = tempfile.TemporaryDirectory(prefix="ares-smoke-logs-", dir=ROOT)
        self.addCleanup(self._assert_temporary_directories_removed)
        self.addCleanup(self.workspace_temp.cleanup)
        self.addCleanup(self.data_temp.cleanup)
        self.addCleanup(self.log_temp.cleanup)
        self.workspace = Path(self.workspace_temp.name)
        self.data_dir = Path(self.data_temp.name)
        self.log_dir = Path(self.log_temp.name)
        (self.workspace / "smoke_edit.py").write_text(BASE_CONTENT, encoding="utf-8")
        (self.workspace / ".env.py").write_text("SYNTHETIC_ONLY = True\n", encoding="utf-8")
        self.initial_names = {path.name for path in self.workspace.iterdir()}

    def _assert_temporary_directories_removed(self) -> None:
        self.assertFalse(Path(self.workspace_temp.name).exists())
        self.assertFalse(Path(self.data_temp.name).exists())
        self.assertFalse(Path(self.log_temp.name).exists())

    def _write_runner_test(self, port: int) -> None:
        (self.workspace / "test_smoke_runner.py").write_text(
            "import os\n"
            "import socket\n"
            "import subprocess\n"
            "import sys\n"
            "import unittest\n"
            "class Smoke(unittest.TestCase):\n"
            " def test_isolation(self):\n"
            "  self.assertIsNone(os.environ.get('GERAM_SYNTHETIC_PARENT_SECRET'))\n"
            "  probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "  probe.settimeout(0.3)\n"
            f"  self.assertNotEqual(probe.connect_ex(('127.0.0.1', {port})), 0)\n"
            "  probe.close()\n"
            f"  child = subprocess.Popen([sys.executable, '-c', \"import time; marker='{DETACHED_MARKER}'; time.sleep(30)\"], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
            "start_new_session=True)\n"
            "  print('detached-pid=' + str(child.pid))\n"
            "  print('runner-smoke-ok network-blocked')\n",
            encoding="utf-8",
        )

    @staticmethod
    def _detail_code(payload: dict) -> str | None:
        detail = payload.get("detail")
        return detail.get("code") if isinstance(detail, dict) else None

    def _read_edit(self, client: HttpClient) -> dict:
        query = urllib.parse.urlencode({"path": "smoke_edit.py"})
        return client.json("GET", f"/api/workspace/file?{query}")

    def _restore_base(self, client: HttpClient) -> None:
        current = self._read_edit(client)
        if current["content"] != BASE_CONTENT:
            client.json(
                "PUT",
                "/api/workspace/file",
                {
                    "path": "smoke_edit.py",
                    "content": BASE_CONTENT,
                    "base_version": current["version"],
                },
                origin=client.local_origin,
            )

    def _propose(self, client: HttpClient) -> dict:
        current = self._read_edit(client)
        return client.json(
            "POST",
            "/api/ares/proposals",
            {
                "instruction": "Make the deterministic synthetic edit",
                "files": [{"path": "smoke_edit.py", "base_version": current["version"]}],
            },
            origin=client.local_origin,
        )

    @staticmethod
    def _approval_payload(proposal: dict) -> dict:
        return {
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
            "approval": True,
            "approved_by": "local_user",
            "files": proposal["files"],
        }

    def _approve(self, client: HttpClient, proposal: dict) -> dict:
        return client.json(
            "POST",
            "/api/ares/proposals/approve",
            self._approval_payload(proposal),
            origin=client.local_origin,
        )

    @staticmethod
    def _apply_payload(proposal: dict, approval: dict) -> dict:
        return {
            "proposal_id": proposal["proposal_id"],
            "proposal_digest": proposal["proposal_digest"],
            "approval_token": approval["approval_token"],
        }

    def test_real_server_edit_and_runner_workflows(self):
        restart_proposal = None
        with SmokeServer(self.workspace, self.data_dir, self.log_dir) as server:
            client = server.client
            self._write_runner_test(server.port)

            openapi = client.json("GET", "/openapi.json")
            paths = set(openapi["paths"])
            required = {
                "/api/ares/proposals",
                "/api/ares/proposals/approve",
                "/api/ares/proposals/apply",
                "/api/ares/proposals/cancel",
                "/api/ares/tests",
            }
            self.assertTrue(required.issubset(paths))

            status, source, _raw = client.request("GET", "/ares-workspace.js")
            self.assertEqual(status, 200)
            self.assertIsInstance(source, str)
            self.assertIn("/api/ares/proposals/approve", source)
            self.assertIn("/api/ares/proposals/apply", source)
            self.assertLess(source.index("if (approval)"), source.index("/api/ares/proposals/apply"))

            current = self._read_edit(client)
            bad_origin_status, _payload, _raw = client.request(
                "POST",
                "/api/ares/proposals",
                {
                    "instruction": "synthetic",
                    "files": [{"path": "smoke_edit.py", "base_version": current["version"]}],
                },
                origin="https://example.invalid",
            )
            self.assertEqual(bad_origin_status, 403)

            invalid_status, _invalid_payload, invalid_raw = client.request(
                "POST",
                "/api/ares/tests",
                {"runner": VALIDATION_MARKER, "target": "test_smoke_runner.py"},
                origin=client.local_origin,
            )
            self.assertEqual(invalid_status, 422)
            self.assertNotIn(VALIDATION_MARKER, invalid_raw)
            self.assertNotIn("Traceback", invalid_raw)

            extra_status, _extra_payload, extra_raw = client.request(
                "POST",
                "/api/ares/proposals",
                {
                    "instruction": "synthetic",
                    "files": [{"path": "smoke_edit.py", "base_version": current["version"]}],
                    "unexpected": VALIDATION_MARKER,
                },
                origin=client.local_origin,
            )
            self.assertEqual(extra_status, 422)
            self.assertNotIn(VALIDATION_MARKER, extra_raw)

            proposal = self._propose(client)
            self.assertEqual(proposal["state"], "proposed")
            self.assertIn("--- a/smoke_edit.py", proposal["diff"])
            self.assertIn("+++ b/smoke_edit.py", proposal["diff"])
            self.assertNotIn(str(self.workspace), json.dumps(proposal))
            self.assertEqual(self._read_edit(client)["content"], BASE_CONTENT)
            no_approval_status, no_approval, _raw = client.request(
                "POST",
                "/api/ares/proposals/apply",
                {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                    "approval_token": "A" * 43,
                },
                origin=client.local_origin,
            )
            self.assertEqual(no_approval_status, 409)
            self.assertEqual(self._detail_code(no_approval), "proposal_not_approved")
            approval = self._approve(client, proposal)
            self.assertEqual(approval["state"], "approved")
            self.assertEqual(self._read_edit(client)["content"], BASE_CONTENT)
            applied = client.json(
                "POST",
                "/api/ares/proposals/apply",
                self._apply_payload(proposal, approval),
                origin=client.local_origin,
            )
            self.assertEqual(applied["state"], "applied")
            self.assertEqual(self._read_edit(client)["content"], PROPOSED_CONTENT)
            self._restore_base(client)

            proposal = self._propose(client)
            approval = self._approve(client, proposal)
            current = self._read_edit(client)
            client.json(
                "PUT",
                "/api/workspace/file",
                {
                    "path": "smoke_edit.py",
                    "content": "VALUE = 'conflict'\n",
                    "base_version": current["version"],
                },
                origin=client.local_origin,
            )
            conflict_status, conflict, _raw = client.request(
                "POST",
                "/api/ares/proposals/apply",
                self._apply_payload(proposal, approval),
                origin=client.local_origin,
            )
            self.assertEqual(conflict_status, 409)
            self.assertEqual(self._detail_code(conflict), "version_conflict")
            self.assertEqual(self._read_edit(client)["content"], "VALUE = 'conflict'\n")
            self._restore_base(client)

            proposal = self._propose(client)
            approval = self._approve(client, proposal)
            apply_payload = self._apply_payload(proposal, approval)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        client.request,
                        "POST",
                        "/api/ares/proposals/apply",
                        apply_payload,
                        origin=client.local_origin,
                    )
                    for _ in range(2)
                ]
                statuses = sorted(future.result()[0] for future in futures)
            self.assertEqual(statuses, [200, 409])
            self.assertEqual(self._read_edit(client)["content"], PROPOSED_CONTENT)
            self._restore_base(client)

            proposal = self._propose(client)
            approval = self._approve(client, proposal)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                apply_future = pool.submit(
                    client.request,
                    "POST",
                    "/api/ares/proposals/apply",
                    self._apply_payload(proposal, approval),
                    origin=client.local_origin,
                )
                cancel_future = pool.submit(
                    client.request,
                    "POST",
                    "/api/ares/proposals/cancel",
                    {
                        "proposal_id": proposal["proposal_id"],
                        "cancel": True,
                        "cancelled_by": "local_user",
                    },
                    origin=client.local_origin,
                )
                race_statuses = sorted([apply_future.result()[0], cancel_future.result()[0]])
            self.assertEqual(race_statuses, [200, 409])
            self.assertIn(self._read_edit(client)["content"], {BASE_CONTENT, PROPOSED_CONTENT})
            self._restore_base(client)

            proposal = self._propose(client)
            approval_payload = self._approval_payload(proposal)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                approve_future = pool.submit(
                    client.request,
                    "POST",
                    "/api/ares/proposals/approve",
                    approval_payload,
                    origin=client.local_origin,
                )
                cancel_future = pool.submit(
                    client.request,
                    "POST",
                    "/api/ares/proposals/cancel",
                    {
                        "proposal_id": proposal["proposal_id"],
                        "cancel": True,
                        "cancelled_by": "local_user",
                    },
                    origin=client.local_origin,
                )
                approve_result = approve_future.result()
                cancel_result = cancel_future.result()
            self.assertEqual(cancel_result[0], 200)
            self.assertIn(approve_result[0], {200, 409})
            if approve_result[0] == 200:
                cancelled_apply_status, _payload, _raw = client.request(
                    "POST",
                    "/api/ares/proposals/apply",
                    self._apply_payload(proposal, approve_result[1]),
                    origin=client.local_origin,
                )
                self.assertEqual(cancelled_apply_status, 409)
            self.assertEqual(self._read_edit(client)["content"], BASE_CONTENT)

            before_runner = _descendants(server.process.pid)
            self.assertFalse(_pids_with_cmdline_marker(DETACHED_MARKER))
            bad_runner_origin, _payload, _raw = client.request(
                "POST",
                "/api/ares/tests",
                {
                    "runner": "python_unittest",
                    "target": "test_smoke_runner.py",
                    "timeout_seconds": 5.0,
                },
                origin="https://example.invalid",
            )
            self.assertEqual(bad_runner_origin, 403)
            self.assertEqual(_descendants(server.process.pid), before_runner)
            runner = client.json(
                "POST",
                "/api/ares/tests",
                {
                    "runner": "python_unittest",
                    "target": "test_smoke_runner.py",
                    "timeout_seconds": 5.0,
                },
                origin=client.local_origin,
            )
            self.assertEqual(runner["status"], "succeeded")
            self.assertEqual(runner["sandbox_backend"], "bubblewrap")
            self.assertEqual(runner["cleanup_status"], "clean")
            self.assertIn("runner-smoke-ok network-blocked", runner["stdout"])
            detached = re.search(r"detached-pid=(\d+)", runner["stdout"])
            self.assertIsNotNone(detached)
            self.assertFalse(_pids_with_cmdline_marker(DETACHED_MARKER))
            self.assertNotIn(PARENT_MARKER, str(runner))
            self.assertNotIn(str(self.workspace), str(runner))
            self.assertEqual(_descendants(server.process.pid), before_runner)

            rejected = client.json(
                "POST",
                "/api/ares/tests",
                {"runner": "python_unittest", "target": ".env.py"},
                origin=client.local_origin,
            )
            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(rejected["cleanup_status"], "not_started")
            restart_proposal = self._propose(client)
            self.assertEqual(self._read_edit(client)["content"], BASE_CONTENT)

        self.assertNotIn(PARENT_MARKER, server.output)
        self.assertEqual((self.workspace / "smoke_edit.py").read_text(), BASE_CONTENT)

        with SmokeServer(self.workspace, self.data_dir, self.log_dir) as restarted:
            status, missing, _raw = restarted.client.request(
                "POST",
                "/api/ares/proposals/approve",
                self._approval_payload(restart_proposal),
                origin=restarted.client.local_origin,
            )
            self.assertEqual(status, 404)
            self.assertEqual(self._detail_code(missing), "proposal_not_found")

            active = [self._propose(restarted.client) for _ in range(32)]
            capacity_status, capacity, _raw = restarted.client.request(
                "POST",
                "/api/ares/proposals",
                {
                    "instruction": "capacity check",
                    "files": [{
                        "path": "smoke_edit.py",
                        "base_version": self._read_edit(restarted.client)["version"],
                    }],
                },
                origin=restarted.client.local_origin,
            )
            self.assertEqual(capacity_status, 503)
            self.assertEqual(self._detail_code(capacity), "proposal_capacity")
            restarted.client.json(
                "POST",
                "/api/ares/proposals/reject",
                {
                    "proposal_id": active[0]["proposal_id"],
                    "rejection": True,
                    "rejected_by": "local_user",
                },
                origin=restarted.client.local_origin,
            )
            replacement = self._propose(restarted.client)
            self.assertEqual(replacement["state"], "proposed")

        with SmokeServer(
            self.workspace,
            self.data_dir,
            self.log_dir,
            disable_bwrap=True,
        ) as unavailable_server:
            self._write_runner_test(unavailable_server.port)
            before = _descendants(unavailable_server.process.pid)
            unavailable = unavailable_server.client.json(
                "POST",
                "/api/ares/tests",
                {
                    "runner": "python_unittest",
                    "target": "test_smoke_runner.py",
                    "timeout_seconds": 5.0,
                },
                origin=unavailable_server.client.local_origin,
            )
            self.assertEqual(unavailable, {
                "status": "unavailable",
                "error": "sandbox_unavailable",
                "cleanup_status": "not_started",
            })
            self.assertEqual(_descendants(unavailable_server.process.pid), before)

        self.assertEqual((self.workspace / "smoke_edit.py").read_text(), BASE_CONTENT)
        self.assertFalse(list(self.workspace.rglob(".geram-workspace-*")))
        self.assertEqual(
            {path.name for path in self.workspace.iterdir()},
            self.initial_names | {"test_smoke_runner.py"},
        )


def _serve() -> None:
    import dotenv

    dotenv.load_dotenv = lambda *_args, **_kwargs: False

    import uvicorn

    from app.api import ares_edits
    from app.api import workspace as workspace_api
    from app.core import test_runner
    from app.core.config import settings
    from app.core.providers.registry import ProviderDispatchResult
    from app.core.sandbox_backend import SandboxUnavailableError
    from app.core.workspace import WorkspaceService
    from app import main

    root = Path(os.environ["GERAM_WORKSPACE_ROOT"]).resolve(strict=True)
    service = WorkspaceService(root)
    settings.WORKSPACE_ROOT = root
    workspace_api.workspace_service = service
    ares_edits.workspace_service = service
    ares_edits.clear_proposals()

    async def fake_provider(_role, _prompt, _configuration=None, **_structured_output):
        current = service.read_file("smoke_edit.py")
        response = {
            "summary": "Synthetic local smoke edit",
            "warnings": [],
            "changes": [{
                "operation": "replace_existing_file",
                "path": "smoke_edit.py",
                "base_version": current["version"],
                "content": PROPOSED_CONTENT,
            }],
        }
        return ProviderDispatchResult(
            result={"text": json.dumps(response)},
            metadata={"provider": "synthetic", "model": "smoke", "fallback_used": False},
        )

    async def no_background_network():
        return None

    ares_edits.provider_registry.generate_for_role = fake_provider
    main.poll_telegram_updates = no_background_network
    main.hud_socket.telemetry_broadcast_loop = no_background_network

    if os.environ.get("GERAM_SMOKE_DISABLE_BWRAP") == "1":
        def unavailable_backend():
            raise SandboxUnavailableError("synthetic smoke unavailability")

        test_runner.detect_sandbox_backend = unavailable_backend

    uvicorn.run(
        main.app,
        host=HOST,
        port=int(os.environ["APP_PORT"]),
        workers=1,
        proxy_headers=False,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    if "--serve" in sys.argv:
        _serve()
    else:
        unittest.main()
