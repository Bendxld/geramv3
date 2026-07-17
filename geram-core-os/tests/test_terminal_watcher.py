import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.api import terminal_watcher as tw

class TerminalWatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tw._runs.clear(); tw._tasks.clear()
    async def wait_status(self, run_id, status):
        for _ in range(100):
            run = await tw.get_run(run_id)
            if run["status"] == status and run["cleanup_status"] != "pending": return run
            await asyncio.sleep(.01)
        self.fail("run did not reach terminal state")
    async def test_stdout_and_success(self):
        with patch.object(tw, "require_local_origin"):
            result = await tw.start_run(None, tw.StartRequest(task="stdout"))
        run = await self.wait_status(result["run_id"], "succeeded")
        self.assertEqual(run["status"], "succeeded"); self.assertIn("stdout", run["stdout"])
        self.assertIsNotNone(run["leader_pid"]); self.assertIsNotNone(run["process_group_id"]); self.assertEqual(run["cleanup_status"], "clean")
    async def test_rejects_arbitrary_fields_and_task(self):
        with self.assertRaises(Exception): await tw.start_run(None, tw.StartRequest(task="nope"))
    async def test_timeout_and_cancel(self):
        with patch.object(tw, "require_local_origin"):
            timeout = await tw.start_run(None, tw.StartRequest(task="timeout", timeout_seconds=0.05))
        timed = await self.wait_status(timeout["run_id"], "timed_out")
        self.assertIn("SIGTERM", timed["signals_sent"])
        self.assertEqual(timed["termination_reason"], "timeout")
        self.assertEqual(timed["cleanup_status"], "clean")
        with patch.object(tw, "require_local_origin"):
            cancel = await tw.start_run(None, tw.StartRequest(task="cancelable"))
            await tw.cancel_run(None, cancel["run_id"])
        cancelled = await self.wait_status(cancel["run_id"], "cancelled")
        self.assertEqual(cancelled["cleanup_status"], "clean")
        self.assertEqual(cancelled["termination_reason"], "cancelled")

    async def test_cancel_finished_run_is_idempotent(self):
        with patch.object(tw, "require_local_origin"):
            result = await tw.start_run(None, tw.StartRequest(task="stdout"))
        await self.wait_status(result["run_id"], "succeeded")
        with patch.object(tw, "require_local_origin"):
            with self.assertRaises(Exception): await tw.cancel_run(None, result["run_id"])
    async def test_stderr_and_failure(self):
        with patch.object(tw, "require_local_origin"):
            err = await tw.start_run(None, tw.StartRequest(task="stderr"))
        self.assertIn("stderr", (await self.wait_status(err["run_id"], "succeeded"))["stderr"])
        with patch.object(tw, "require_local_origin"):
            fail = await tw.start_run(None, tw.StartRequest(task="failure"))
        self.assertEqual((await self.wait_status(fail["run_id"], "failed"))["status"], "failed")

    async def test_python_runner_never_spawns_without_valid_bubblewrap_prefix(self):
        run = tw.Run(
            "closed",
            "python_unittest",
            ["/usr/bin/python3", "-m", "unittest", "test_x.py"],
            ".",
            sandbox_env={
                "PATH": "/usr/bin:/bin",
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": "/opt/geram",
                "HOME": "/tmp/home",
            },
        )
        spawn = AsyncMock()
        with patch.object(tw.asyncio, "create_subprocess_exec", new=spawn):
            await tw._capture(run, 1)
        self.assertEqual(run.status, "spawn_error")
        self.assertEqual(run.termination_reason, "spawn_error")
        self.assertEqual(run.cleanup_status, "not_started")
        spawn.assert_not_awaited()

    async def test_python_file_runner_never_spawns_without_valid_bubblewrap_prefix(self):
        run = tw.Run(
            "closed-file",
            "python_file",
            ["/usr/bin/python3", "main.py"],
            ".",
            sandbox_env={
                "PATH": "/usr/bin:/bin",
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": "/opt/geram",
                "HOME": "/tmp/home",
            },
        )
        spawn = AsyncMock()
        with patch.object(tw.asyncio, "create_subprocess_exec", new=spawn):
            await tw._capture(run, 1)
        self.assertEqual(run.status, "spawn_error")
        spawn.assert_not_awaited()

    async def test_node_runner_never_spawns_without_valid_bubblewrap_prefix(self):
        node = tw.trusted_node_executable()
        self.assertIsNotNone(node)
        run = tw.Run(
            "closed-node", "node_script", [str(node), "--", "index.js"], ".",
            sandbox_env={
                "PATH": "/usr/bin:/bin", "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": "/opt/geram", "HOME": "/tmp/home",
            },
        )
        spawn = AsyncMock()
        with patch.object(tw.asyncio, "create_subprocess_exec", new=spawn):
            await tw._capture(run, 1)
        self.assertEqual(run.status, "spawn_error")
        spawn.assert_not_awaited()

    def test_output_sanitizer_removes_terminal_controls_redacts_and_bounds_bytes(self):
        raw = (
            b"\x1b[31mTOKEN=synthetic-value\x00\n"
            + ("á" * tw.MAX_OUTPUT).encode("utf-8")
        )
        sanitized = tw._sanitize_output(raw, truncated=True)
        self.assertNotIn("\x1b", sanitized)
        self.assertNotIn("\x00", sanitized)
        self.assertNotIn("synthetic-value", sanitized)
        self.assertIn("TOKEN=[REDACTED]", sanitized)
        self.assertIn("[output truncated]", sanitized)
        self.assertLessEqual(len(sanitized.encode("utf-8")), tw.MAX_OUTPUT)
