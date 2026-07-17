import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.api import ares_edits
from app.api import terminal_watcher
from app.api.ares_edits import AresTestRequest, run_project_test, start_ares_test
from app.core.sandbox_backend import SandboxUnavailableError
from app.core.security import require_local_origin, require_localhost


class AresTestRunnerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        terminal_watcher._runs.clear()
        terminal_watcher._tasks.clear()

    async def _run(self, root: Path, target: str, timeout: float = 5.0, *, capture=False, runner="python_unittest"):
        created = []
        real_run = terminal_watcher.Run

        def record(*args, **kwargs):
            run = real_run(*args, **kwargs)
            created.append(run)
            return run

        with patch("app.core.test_runner.settings.WORKSPACE_ROOT", str(root)):
            if capture:
                with patch("app.core.test_runner.terminal_watcher.Run", side_effect=record):
                    result = await run_project_test(
                        AresTestRequest(
                            runner=runner,
                            target=target,
                            timeout_seconds=timeout,
                        )
                    )
            else:
                result = await run_project_test(
                    AresTestRequest(
                        runner=runner,
                        target=target,
                        timeout_seconds=timeout,
                    )
                )
        return result, created

    async def test_ares_runs_only_the_closed_unittest_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_example.py").write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                " def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            result, created = await self._run(root, "test_example.py", capture=True)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["sandbox_backend"], "bubblewrap")
        self.assertEqual(result["cleanup_status"], "clean")
        self.assertNotIn("argv", result)
        self.assertNotIn(str(root), str(result))
        self.assertEqual(len(created), 1)
        run = created[0]
        self.assertEqual(run.argv, ["/usr/bin/python3", "-m", "unittest", "test_example.py"])
        self.assertEqual(run.cwd, ".")
        self.assertEqual(run.sandbox_env, {
            "PATH": "/usr/bin:/bin",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": "/opt/geram",
            "HOME": "/tmp/home",
        })
        self.assertEqual(run.sandbox_prefix[-1], "--")
        self.assertIn("--unshare-all", run.sandbox_prefix)
        self.assertNotIn("--share-net", run.sandbox_prefix)

    async def test_ares_executes_a_python_file_with_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.py").write_text(
                "import sys\nprint('file-out')\nprint('file-err', file=sys.stderr)\n",
                encoding="utf-8",
            )
            result, created = await self._run(root, "main.py", capture=True, runner="python_file")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("file-out", result["stdout"])
        self.assertIn("file-err", result["stderr"])
        self.assertEqual(result["sandbox_backend"], "bubblewrap")
        self.assertEqual(result["cleanup_status"], "clean")
        self.assertEqual(created[0].argv, ["/usr/bin/python3", "main.py"])

    async def test_node_script_captures_stdout_and_uses_exact_closed_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.js").write_text("console.log('node-output')\n", encoding="utf-8")
            result, created = await self._run(root, "index.js", capture=True, runner="node_script")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("node-output", result["stdout"])
        self.assertEqual(result["sandbox_backend"], "bubblewrap")
        self.assertEqual(result["cleanup_status"], "clean")
        self.assertEqual(created[0].argv[1:], ["--", "index.js"])
        self.assertEqual(created[0].argv[0], "/usr/bin/node")

    async def test_node_syntax_error_and_nonzero_exit_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "syntax.js").write_text("function {\n", encoding="utf-8")
            (root / "failure.js").write_text("process.exit(7)\n", encoding="utf-8")
            syntax, _ = await self._run(root, "syntax.js", runner="node_script")
            failure, _ = await self._run(root, "failure.js", runner="node_script")

        self.assertEqual(syntax["status"], "failed")
        self.assertNotEqual(syntax["exit_code"], 0)
        self.assertIn("SyntaxError", syntax["stderr"])
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["exit_code"], 7)

    async def test_node_timeout_and_cleanup_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "timeout.js").write_text("setTimeout(() => {}, 60000)\n", encoding="utf-8")
            result, _ = await self._run(root, "timeout.js", timeout=0.2, runner="node_script")

        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(result["termination_reason"], "timeout")
        self.assertEqual(result["cleanup_status"], "clean")

    async def test_node_network_is_blocked_inside_bubblewrap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "network.js").write_text(
                "const net = require('net');\n"
                "const socket = net.connect(9, '127.0.0.1');\n"
                "socket.on('connect', () => process.exit(9));\n"
                "socket.on('error', () => { console.log('network-blocked'); process.exit(0); });\n"
                "setTimeout(() => process.exit(8), 1000);\n",
                encoding="utf-8",
            )
            result, created = await self._run(root, "network.js", runner="node_script", capture=True)

        self.assertEqual(result["status"], "succeeded")
        self.assertIn("network-blocked", result["stdout"])
        self.assertIn("--unshare-all", created[0].sandbox_prefix)
        self.assertNotIn("--share-net", created[0].sandbox_prefix)

    async def test_node_rejects_unsafe_targets_and_missing_runtime_without_spawn(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            (root / "index.js").write_text("", encoding="utf-8")
            outside = Path(external) / "outside.js"
            outside.write_text("", encoding="utf-8")
            (root / "external.js").symlink_to(outside)
            for target in ("../index.js", str(outside), "index.py", "external.js"):
                with self.subTest(target=target):
                    result, _ = await self._run(root, target, runner="node_script")
                    self.assertEqual(result["status"], "rejected")
                    self.assertEqual(result["cleanup_status"], "not_started")
            spawn = AsyncMock()
            with (
                patch("app.core.test_runner.settings.WORKSPACE_ROOT", str(root)),
                patch("app.core.sandbox_guard.trusted_node_executable", return_value=None),
                patch("app.api.terminal_watcher.asyncio.create_subprocess_exec", new=spawn),
            ):
                missing = await run_project_test(AresTestRequest(runner="node_script", target="index.js"))

        self.assertEqual(missing["status"], "rejected")
        self.assertEqual(missing["error"], "node_unavailable")
        spawn.assert_not_awaited()

    async def test_async_ares_run_is_visible_and_cancellable_through_terminal_watcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "slow.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
            with patch("app.core.test_runner.settings.WORKSPACE_ROOT", str(root)):
                started = await start_ares_test(AresTestRequest(
                    runner="python_file", target="slow.py", timeout_seconds=30,
                ))
                self.assertEqual(started["status"], "queued")
                self.assertEqual(started["sandbox_backend"], "bubblewrap")
                for _ in range(200):
                    current = await terminal_watcher.get_run(started["run_id"])
                    if current["status"] == "running":
                        break
                    await asyncio.sleep(0.01)
                with patch.object(terminal_watcher, "require_local_origin"):
                    await terminal_watcher.cancel_run(None, started["run_id"])
                for _ in range(200):
                    current = await terminal_watcher.get_run(started["run_id"])
                    if current["status"] == "cancelled" and current["cleanup_status"] == "clean":
                        break
                    await asyncio.sleep(0.01)

        self.assertEqual(current["status"], "cancelled")
        self.assertEqual(current["cleanup_status"], "clean")
        self.assertEqual(current["sandbox_backend"], "bubblewrap")

    async def test_async_node_run_is_cancellable_and_cleans_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "slow.js").write_text("setTimeout(() => {}, 60000)\n", encoding="utf-8")
            with patch("app.core.test_runner.settings.WORKSPACE_ROOT", str(root)):
                started = await start_ares_test(AresTestRequest(
                    runner="node_script", target="slow.js", timeout_seconds=30,
                ))
                for _ in range(200):
                    current = await terminal_watcher.get_run(started["run_id"])
                    if current["status"] == "running" and current["leader_pid"]:
                        break
                    await asyncio.sleep(0.01)
                with patch.object(terminal_watcher, "require_local_origin"):
                    await terminal_watcher.cancel_run(None, started["run_id"])
                for _ in range(200):
                    current = await terminal_watcher.get_run(started["run_id"])
                    if current["status"] == "cancelled" and current["cleanup_status"] == "clean":
                        break
                    await asyncio.sleep(0.01)

        self.assertEqual(current["status"], "cancelled")
        self.assertEqual(current["termination_reason"], "cancelled")
        self.assertEqual(current["cleanup_status"], "clean")
        self.assertEqual(current["sandbox_backend"], "bubblewrap")

    async def test_endpoint_contract_rejects_extra_fields_and_general_execution(self):
        invalid_payloads = (
            {"runner": "pytest", "target": "test_x.py"},
            {"runner": "python_unittest", "target": "test_x.py", "argv": ["-v"]},
            {"runner": "python_unittest", "target": "test_x.py", "cwd": "/tmp"},
            {"runner": "python_unittest", "target": "test_x.py", "environment": {}},
            {"runner": "python_unittest", "target": "test_x.py", "mounts": []},
            {"runner": "python_unittest", "target": "test_x.py", "shell": True},
            {"runner": "python_unittest", "target": "test_x.py", "flags": ["-v"]},
            {"runner": "python_unittest", "target": "test_x.py", "workspace_id": "other"},
            {"runner": "python_unittest", "target": "test_x.py", "timeout_seconds": "1"},
            {"runner": "python_file", "target": "test_x.py", "args": ["--unsafe"]},
            {"runner": "node_script", "target": "index.js", "args": ["--eval"]},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                AresTestRequest.model_validate(payload)

        routes = {route.path: route for route in ares_edits.router.routes}
        dependencies = {
            dependency.call
            for dependency in routes["/api/ares/tests"].dependant.dependencies
        }
        self.assertIn(require_localhost, dependencies)
        self.assertIn(require_local_origin, dependencies)
        async_dependencies = {
            dependency.call
            for dependency in routes["/api/ares/tests/runs"].dependant.dependencies
        }
        self.assertIn(require_localhost, async_dependencies)
        self.assertIn(require_local_origin, async_dependencies)

    async def test_rejects_absolute_traversal_missing_sensitive_and_option_targets(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            (root / ".git").mkdir()
            (root / ".git" / "test_hook.py").write_text("", encoding="utf-8")
            (root / ".env.py").write_text("", encoding="utf-8")
            (root / "cache.sqlite").mkdir()
            (root / "cache.sqlite" / "test_db.py").write_text("", encoding="utf-8")
            (root / "--verbose.py").write_text("", encoding="utf-8")
            (root / "bad\\name.py").write_text("", encoding="utf-8")
            (root / "bad\nname.py").write_text("", encoding="utf-8")
            outside = Path(external) / "outside.py"
            outside.write_text("", encoding="utf-8")
            targets = (
                str(outside),
                "../outside.py",
                "missing.py",
                "notes.txt",
                ".git/test_hook.py",
                ".env.py",
                "cache.sqlite/test_db.py",
                "--verbose.py",
                "bad\\name.py",
                "bad\nname.py",
            )
            for target in targets:
                with self.subTest(target=target):
                    result, _ = await self._run(root, target)
                    self.assertEqual(result["status"], "rejected")
                    self.assertEqual(result["cleanup_status"], "not_started")

    async def test_allows_internal_python_symlink_and_rejects_external_or_non_python_target(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            (root / "test_real.py").write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                " def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (root / "test_internal.py").symlink_to("test_real.py")
            outside = Path(external) / "test_outside.py"
            outside.write_text("", encoding="utf-8")
            (root / "test_external.py").symlink_to(outside)
            (root / ".env").write_text("SYNTHETIC_ONLY=marker\n", encoding="utf-8")
            (root / "test_non_python.py").symlink_to(".env")

            internal, _ = await self._run(root, "test_internal.py")
            external_result, _ = await self._run(root, "test_external.py")
            non_python, _ = await self._run(root, "test_non_python.py")

        self.assertEqual(internal["status"], "succeeded")
        self.assertEqual(external_result["status"], "rejected")
        self.assertEqual(non_python["status"], "rejected")

    async def test_sensitive_workspace_files_and_parent_secret_are_not_visible(self):
        marker = "synthetic-parent-secret-7f41"
        file_marker = "synthetic-file-secret-6a20"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(file_marker, encoding="utf-8")
            os.link(root / ".env", root / "env-hardlink.txt")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text(file_marker, encoding="utf-8")
            (root / "state.sqlite3").write_text(file_marker, encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / ".env.local").write_text(file_marker, encoding="utf-8")
            (root / "test_isolation.py").write_text(
                "import os\n"
                "import unittest\n"
                "from pathlib import Path\n"
                "class T(unittest.TestCase):\n"
                " def test_hidden(self):\n"
                "  self.assertIsNone(os.environ.get('GERAM_SYNTHETIC_PARENT_SECRET'))\n"
                "  for name in ('.env', 'env-hardlink.txt', '.git/config', 'state.sqlite3', 'nested/.env.local'):\n"
                "   try: content = Path(name).read_text()\n"
                "   except (OSError, UnicodeError): content = ''\n"
                f"   self.assertNotIn('{file_marker}', content)\n"
                "  print('isolation-ok')\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GERAM_SYNTHETIC_PARENT_SECRET": marker}):
                result, _ = await self._run(root, "test_isolation.py")

        self.assertEqual(result["status"], "succeeded")
        self.assertIn("isolation-ok", result["stdout"])
        self.assertNotIn(marker, str(result))
        self.assertNotIn(file_marker, str(result))

    async def test_stdout_and_stderr_are_sanitized_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_output.py").write_text(
                "import sys\n"
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                " def test_output(self):\n"
                "  print(chr(27) + '[31mAPI_KEY=synthetic-output-secret' + chr(0) + chr(0x202e))\n"
                "  print('x' * 100000)\n"
                "  print(chr(27) + '[31mPASSWORD=synthetic-error-secret' + chr(0), file=sys.stderr)\n"
                "  print('y' * 100000, file=sys.stderr)\n",
                encoding="utf-8",
            )
            result, _ = await self._run(root, "test_output.py")

        self.assertEqual(result["status"], "succeeded")
        self.assertNotIn("synthetic-output-secret", result["stdout"])
        self.assertIn("API_KEY=[REDACTED]", result["stdout"])
        self.assertNotIn("\x1b", result["stdout"])
        self.assertNotIn("\x00", result["stdout"])
        self.assertNotIn("\u202e", result["stdout"])
        self.assertIn("[output truncated]", result["stdout"])
        self.assertNotIn("synthetic-error-secret", result["stderr"])
        self.assertIn("PASSWORD=[REDACTED]", result["stderr"])
        self.assertNotIn("\x1b", result["stderr"])
        self.assertNotIn("\x00", result["stderr"])
        self.assertIn("[output truncated]", result["stderr"])
        self.assertLessEqual(len(result["stdout"].encode("utf-8")), terminal_watcher.MAX_OUTPUT)
        self.assertLessEqual(len(result["stderr"].encode("utf-8")), terminal_watcher.MAX_OUTPUT)

    async def test_timeout_cleans_resistant_descendants_without_touching_unrelated_process(self):
        outsider = subprocess.Popen(
            ["/usr/bin/python3", "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "test_timeout.py").write_text(
                    "import signal\n"
                    "import subprocess\n"
                    "import sys\n"
                    "import time\n"
                    "subprocess.Popen([sys.executable, '-c', "
                    "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'], "
                    "start_new_session=True)\n"
                    "print('child-ready', flush=True)\n"
                    "time.sleep(60)\n",
                    encoding="utf-8",
                )
                result, created = await self._run(
                    root,
                    "test_timeout.py",
                    timeout=0.4,
                    capture=True,
                )

            self.assertEqual(result["status"], "timed_out")
            self.assertEqual(result["termination_reason"], "timeout")
            self.assertEqual(result["cleanup_status"], "clean")
            self.assertLess(result["duration_seconds"], 2.0)
            self.assertIsNone(outsider.poll())
            self.assertEqual(len(created), 1)
            self.assertTrue(created[0].known_descendant_pids)
            self.assertFalse(any(
                Path("/proc", str(pid)).exists()
                for pid in [created[0].leader_pid, *created[0].known_descendant_pids]
                if pid
            ))
        finally:
            outsider.terminate()
            try:
                outsider.wait(timeout=2)
            except subprocess.TimeoutExpired:
                outsider.kill()
                outsider.wait(timeout=2)

    async def test_cancellation_terminates_the_job_and_reports_clean_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_cancel.py").write_text(
                "import time\n"
                "print('ready', flush=True)\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            created = []
            real_run = terminal_watcher.Run

            def record(*args, **kwargs):
                run = real_run(*args, **kwargs)
                created.append(run)
                return run

            with (
                patch("app.core.test_runner.settings.WORKSPACE_ROOT", str(root)),
                patch("app.core.test_runner.terminal_watcher.Run", side_effect=record),
            ):
                task = asyncio.create_task(run_project_test(AresTestRequest(
                    runner="python_unittest",
                    target="test_cancel.py",
                    timeout_seconds=30,
                )))
                for _ in range(200):
                    if created and created[0].leader_pid:
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(created and created[0].leader_pid)
                await asyncio.sleep(0.1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        run = created[0]
        self.assertEqual(run.status, "cancelled")
        self.assertEqual(run.termination_reason, "cancelled")
        self.assertEqual(run.cleanup_status, "clean")
        self.assertFalse(any(
            Path("/proc", str(pid)).exists()
            for pid in [run.leader_pid, *run.known_descendant_pids]
            if pid
        ))

    async def test_missing_or_invalid_bubblewrap_never_falls_back_to_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_example.py").write_text("", encoding="utf-8")
            spawn = AsyncMock()
            with (
                patch("app.core.test_runner.settings.WORKSPACE_ROOT", str(root)),
                patch(
                    "app.core.test_runner.detect_sandbox_backend",
                    side_effect=SandboxUnavailableError("synthetic"),
                ),
                patch("app.api.terminal_watcher.asyncio.create_subprocess_exec", new=spawn),
            ):
                unavailable = await run_project_test(AresTestRequest(
                    runner="python_unittest",
                    target="test_example.py",
                ))
            self.assertEqual(unavailable["status"], "unavailable")
            self.assertEqual(unavailable["error"], "sandbox_unavailable")
            self.assertEqual(unavailable["cleanup_status"], "not_started")
            spawn.assert_not_awaited()

            spawn = AsyncMock()
            with (
                patch("app.core.test_runner.settings.WORKSPACE_ROOT", str(root)),
                patch("app.core.test_runner.build_sandbox_prefix", return_value=[]),
                patch("app.api.terminal_watcher.asyncio.create_subprocess_exec", new=spawn),
            ):
                invalid = await run_project_test(AresTestRequest(
                    runner="python_unittest",
                    target="test_example.py",
                ))
            self.assertEqual(invalid["status"], "spawn_error")
            self.assertEqual(invalid["cleanup_status"], "not_started")
            spawn.assert_not_awaited()

    async def test_internal_errors_and_nonzero_exit_are_closed_and_sanitized(self):
        with patch.object(
            ares_edits,
            "run_test",
            side_effect=RuntimeError("synthetic-internal-secret"),
        ):
            error = await run_project_test(AresTestRequest(
                runner="python_unittest",
                target="test_example.py",
            ))
        self.assertEqual(error, {
            "status": "unavailable",
            "error": "test_runner_error",
            "cleanup_status": "not_started",
        })
        self.assertNotIn("synthetic-internal-secret", str(error))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_failure.py").write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                " def test_failure(self): self.fail('synthetic failure')\n",
                encoding="utf-8",
            )
            failed, _ = await self._run(root, "test_failure.py")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["termination_reason"], "exit_nonzero")
        self.assertEqual(failed["cleanup_status"], "clean")


if __name__ == "__main__":
    unittest.main()
