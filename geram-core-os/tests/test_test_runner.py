import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.core.test_runner import TestRunSpec, run_unittest
from app.core.sandbox_backend import SandboxUnavailableError

class TestRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_internal_unittest_runs_in_sandbox(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "test_example.py"; path.write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n", encoding="utf-8")
            with patch("app.core.test_runner.settings.WORKSPACE_ROOT", root):
                result = await run_unittest(TestRunSpec("python_unittest", "test_example.py", 10))
        self.assertIn(result["status"], {"succeeded", "failed"}); self.assertEqual(result["sandbox_backend"], "bubblewrap")
    async def test_rejects_target_and_runner(self):
        self.assertEqual((await run_unittest(TestRunSpec("pytest", "x.py")))["status"], "rejected")
        self.assertEqual((await run_unittest(TestRunSpec("python_unittest", "../x.py")))["status"], "rejected")

    async def test_rejects_absolute_symlink_and_non_python(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as external:
            workspace = Path(root); outside = Path(external) / "outside.py"; outside.write_text("", encoding="utf-8")
            (workspace / "link.py").symlink_to(outside); (workspace / "note.txt").write_text("x", encoding="utf-8")
            with patch("app.core.test_runner.settings.WORKSPACE_ROOT", root):
                self.assertEqual((await run_unittest(TestRunSpec("python_unittest", "link.py")))["status"], "rejected")
                self.assertEqual((await run_unittest(TestRunSpec("python_unittest", "note.txt")))["status"], "rejected")

    async def test_unavailable_backend_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "test_example.py").write_text("", encoding="utf-8")
            with patch("app.core.test_runner.settings.WORKSPACE_ROOT", root), patch("app.core.test_runner.detect_sandbox_backend", side_effect=SandboxUnavailableError("hidden")):
                self.assertEqual((await run_unittest(TestRunSpec("python_unittest", "test_example.py")))["status"], "unavailable")
