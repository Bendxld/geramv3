import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from app.core.sandbox_guard import (
    ExecutionSpec,
    authorize,
    authorize_node_script,
    authorize_python_file,
    authorize_unittest,
    environment,
    is_sensitive_workspace_path,
    trusted_node_executable,
)

class SandboxGuardTests(unittest.TestCase):
    def test_valid_closed_task(self):
        d = authorize(ExecutionSpec("stdout", "synthetic_python_module")); self.assertTrue(d.allowed); self.assertEqual(d.policy_version, 1)
    def test_fail_closed_matrix(self):
        cases = [ExecutionSpec("unknown", "synthetic_python_module"), ExecutionSpec("stdout", "bash"), ExecutionSpec("stdout", "synthetic_python_module", ("-c",)), ExecutionSpec("stdout", "synthetic_python_module", cwd="/tmp"), ExecutionSpec("stdout", "synthetic_python_module", network_policy="allow")]
        self.assertTrue(all(not authorize(c).allowed for c in cases))
    def test_environment_is_minimal(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY":"synthetic", "HTTP_PROXY":"synthetic"}):
            env = environment()
        self.assertNotIn("OPENAI_API_KEY", env); self.assertNotIn("HTTP_PROXY", env); self.assertEqual(env["PYTHONPATH"].split("/")[-1], "geram-core-os")

    def test_unittest_target_is_canonical_existing_python_inside_workspace(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            (root / "test_real.py").write_text("", encoding="utf-8")
            (root / "test_link.py").symlink_to("test_real.py")
            outside = Path(external) / "test_external.py"
            outside.write_text("", encoding="utf-8")
            (root / "test_external.py").symlink_to(outside)
            with mock.patch("app.core.sandbox_guard.settings.WORKSPACE_ROOT", root):
                self.assertTrue(authorize_unittest("test_link.py", 1).allowed)
                for target in (
                    "/tmp/test.py",
                    "../test.py",
                    "missing.py",
                    "test_external.py",
                    "--verbose.py",
                    "bad\\name.py",
                    "bad\nname.py",
                ):
                    with self.subTest(target=target):
                        self.assertFalse(authorize_unittest(target, 1).allowed)
                for timeout in (0, 61, float("inf"), float("nan"), True, "1"):
                    with self.subTest(timeout=timeout):
                        self.assertFalse(authorize_unittest("test_real.py", timeout).allowed)

    def test_python_file_profile_has_fixed_interpreter_and_no_free_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
            with mock.patch("app.core.sandbox_guard.settings.WORKSPACE_ROOT", root):
                decision = authorize_python_file("main.py", 10)
                self.assertTrue(decision.allowed)
                self.assertEqual(decision.spec.args, ("/usr/bin/python3", "main.py"))
                self.assertFalse(authorize_python_file("main.py -c pass", 10).allowed)
                self.assertFalse(authorize_python_file("../main.py", 10).allowed)

    def test_node_script_contract_is_relative_javascript_without_user_arguments(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            (root / "index.js").write_text("console.log('ok')\n", encoding="utf-8")
            outside = Path(external) / "outside.js"
            outside.write_text("", encoding="utf-8")
            (root / "external.js").symlink_to(outside)
            with mock.patch("app.core.sandbox_guard.settings.WORKSPACE_ROOT", root):
                decision = authorize_node_script("index.js", 10)
                self.assertTrue(decision.allowed)
                self.assertEqual(decision.spec.args, (str(trusted_node_executable()), "--", "index.js"))
                for target in (
                    "/tmp/index.js", "../index.js", "index.py", "missing.js",
                    "external.js", "--eval.js", "bad\\name.js", "bad\nname.js",
                ):
                    with self.subTest(target=target):
                        self.assertFalse(authorize_node_script(target, 10).allowed)

    def test_node_script_fails_closed_when_system_node_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.js").write_text("", encoding="utf-8")
            with (
                mock.patch("app.core.sandbox_guard.settings.WORKSPACE_ROOT", root),
                mock.patch("app.core.sandbox_guard._TRUSTED_NODE_PATHS", (root / "missing-node",)),
            ):
                decision = authorize_node_script("index.js", 10)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "node_unavailable")

    def test_sensitive_path_policy_covers_env_vcs_databases_and_private_keys(self):
        for path in (
            ".env",
            "nested/.env.local",
            ".git/config",
            "nested/.hg/store",
            "state.sqlite3",
            "state.sqlite-wal",
            "state.db-wal",
            "credentials.json",
            "certificate.pem",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_sensitive_workspace_path(path))
        self.assertFalse(is_sensitive_workspace_path("tests/test_credentials.py"))
