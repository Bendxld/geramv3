import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.api import testing
from app.core.security import require_localhost
from app.main import app
from app.core.sandbox_backend import SandboxUnavailableError
from app.core.test_discovery import UnittestDiscovery
from app.core.test_runner import TestRunSpec, run_test
from app.core.workspace import WorkspaceService


class UnittestDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "tests").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_static_discovery_finds_classes_methods_aliases_and_lines(self):
        (self.root / "tests/test_math.py").write_text(
            "import unittest as unit\n"
            "class MathTests(unit.TestCase):\n"
            "    def test_add(self): pass\n"
            "    def helper(self): pass\n"
            "    async def test_async(self): pass\n",
            encoding="utf-8",
        )
        result = UnittestDiscovery(WorkspaceService(self.root)).discover()
        self.assertEqual(result["total"], 2)
        file = result["files"][0]
        self.assertEqual(file["path"], "tests/test_math.py")
        self.assertEqual(file["classes"][0]["selector"], "MathTests")
        self.assertEqual([item["selector"] for item in file["classes"][0]["methods"]], ["MathTests.test_add", "MathTests.test_async"])
        self.assertEqual(file["classes"][0]["methods"][0]["line"], 3)

    def test_discovery_never_imports_and_ignores_syntax_sensitive_and_excluded(self):
        marker = self.root / "executed"
        (self.root / "tests/test_safe.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            "from unittest import TestCase as Case\nclass Safe(Case):\n    def test_ok(self): pass\n",
            encoding="utf-8",
        )
        (self.root / "tests/broken.py").write_text("class (", encoding="utf-8")
        (self.root / ".env.py").write_text("import unittest\nclass Hidden(unittest.TestCase):\n def test_secret(self): pass\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules/test_bad.py").write_text("import unittest\n", encoding="utf-8")
        result = UnittestDiscovery(WorkspaceService(self.root)).discover()
        self.assertFalse(marker.exists())
        self.assertEqual([item["path"] for item in result["files"]], ["tests/test_safe.py"])


class SelectedRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_class_and_method_use_existing_bubblewrap_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_sample.py").write_text(
                "import unittest\n"
                "class First(unittest.TestCase):\n"
                " def test_ok(self): print('FIRST_OK')\n"
                " def test_bad(self): self.fail('intentional')\n"
                "class Second(unittest.TestCase):\n"
                " def test_ok(self): print('SECOND_OK')\n",
                encoding="utf-8",
            )
            with patch("app.core.test_runner.settings.WORKSPACE_ROOT", root), patch("app.core.sandbox_guard.settings.WORKSPACE_ROOT", root), patch("app.api.terminal_watcher.settings.WORKSPACE_ROOT", root):
                method = await run_test(TestRunSpec("python_unittest", "test_sample.py", 20, "First.test_ok"))
                selected_class = await run_test(TestRunSpec("python_unittest", "test_sample.py", 20, "Second"))
                all_file = await run_test(TestRunSpec("python_unittest", "test_sample.py", 20))
        self.assertEqual(method["status"], "succeeded")
        self.assertIn("FIRST_OK", method["stdout"])
        self.assertNotIn("SECOND_OK", method["stdout"])
        self.assertEqual(selected_class["status"], "succeeded")
        self.assertIn("SECOND_OK", selected_class["stdout"])
        self.assertEqual(all_file["status"], "failed")
        for result in (method, selected_class, all_file):
            self.assertEqual(result["sandbox_backend"], "bubblewrap")
            self.assertEqual(result["cleanup_status"], "clean")

    async def test_invalid_selector_traversal_sensitive_and_missing_sandbox_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_sample.py").write_text("import unittest\n", encoding="utf-8")
            (root / ".env.py").write_text("import unittest\n", encoding="utf-8")
            with patch("app.core.test_runner.settings.WORKSPACE_ROOT", root), patch("app.core.sandbox_guard.settings.WORKSPACE_ROOT", root):
                for spec in (
                    TestRunSpec("python_unittest", "test_sample.py", 10, "bad selector"),
                    TestRunSpec("python_unittest", "../test_sample.py"),
                    TestRunSpec("python_unittest", ".env.py"),
                ):
                    self.assertEqual((await run_test(spec))["status"], "rejected")
                with patch("app.core.test_runner.detect_sandbox_backend", side_effect=SandboxUnavailableError("missing")):
                    unavailable = await run_test(TestRunSpec("python_unittest", "test_sample.py"))
                    self.assertEqual(unavailable["status"], "unavailable")

    async def test_javascript_success_and_failure_reuse_closed_node_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ok.js").write_text("console.log('NODE_OK')\n", encoding="utf-8")
            (root / "bad.js").write_text("const = broken\n", encoding="utf-8")
            patches = (
                patch("app.core.test_runner.settings.WORKSPACE_ROOT", root),
                patch("app.core.sandbox_guard.settings.WORKSPACE_ROOT", root),
                patch("app.api.terminal_watcher.settings.WORKSPACE_ROOT", root),
            )
            with patches[0], patches[1], patches[2]:
                passed = await run_test(TestRunSpec("node_script", "ok.js", 20))
                failed = await run_test(TestRunSpec("node_script", "bad.js", 20))
        self.assertEqual(passed["status"], "succeeded")
        self.assertIn("NODE_OK", passed["stdout"])
        self.assertEqual(failed["status"], "failed")
        self.assertNotEqual(failed["exit_code"], 0)
        for result in (passed, failed):
            self.assertEqual(result["sandbox_backend"], "bubblewrap")
            self.assertEqual(result["cleanup_status"], "clean")


class TestingApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "test_api.py").write_text(
            "import unittest\nclass ApiTests(unittest.TestCase):\n def test_ok(self): pass\n",
            encoding="utf-8",
        )
        self.previous = testing.discovery
        testing.discovery = UnittestDiscovery(WorkspaceService(self.root))
        app.dependency_overrides[require_localhost] = lambda: None
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")
        self.headers = {"Origin": "http://127.0.0.1:8000"}

    def tearDown(self):
        testing.discovery = self.previous
        app.dependency_overrides.pop(require_localhost, None)
        self.temporary.cleanup()

    def test_discovery_contract_and_run_schema_are_closed(self):
        response = self.client.get("/api/testing/discovery")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["files"][0]["classes"][0]["methods"][0]["selector"], "ApiTests.test_ok")
        external = self.client.post(
            "/api/testing/runs", json={"runner": "python_unittest", "target": "test_api.py"},
            headers={"Origin": "https://evil.invalid"},
        )
        self.assertEqual(external.status_code, 403)
        extra = self.client.post(
            "/api/testing/runs",
            json={"runner": "python_unittest", "target": "test_api.py", "selector": "ApiTests.test_ok", "command": "pytest"},
            headers=self.headers,
        )
        self.assertEqual(extra.status_code, 422)

    def test_start_response_is_minimal_and_unexpected_errors_are_sanitized(self):
        queued = {
            "run_id": "safe-id", "status": "queued", "runner": "python_unittest",
            "target": "test_api.py", "selector": "ApiTests.test_ok",
            "sandbox_backend": "bubblewrap", "leader_pid": 4321, "argv": ["secret"],
        }
        with patch("app.api.testing.start_test", return_value=queued):
            response = self.client.post(
                "/api/testing/runs",
                json={"runner": "python_unittest", "target": "test_api.py", "selector": "ApiTests.test_ok"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run_id"], "safe-id")
        self.assertNotIn("leader_pid", response.json())
        self.assertNotIn("argv", response.json())
        with patch("app.api.testing.start_test", side_effect=RuntimeError("private details")):
            response = self.client.post(
                "/api/testing/runs",
                json={"runner": "python_unittest", "target": "test_api.py"},
                headers=self.headers,
            )
        self.assertEqual(response.json(), {
            "status": "unavailable", "error": "testing_runner_error", "cleanup_status": "not_started",
        })


if __name__ == "__main__":
    unittest.main()
