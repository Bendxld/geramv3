import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.git_service import GitService
from app.core.workspace import WorkspaceError, WorkspaceService
from app.api import source_control
from app.core.security import require_localhost
from app.main import app
from fastapi.testclient import TestClient


class GitServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temporary.name)
        self.root = self.workspace_root / "project"
        self.root.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.name", "GERAM Test")
        self._git("config", "user.email", "geram-test@example.invalid")
        (self.root / "main.py").write_text("value = 1\n", encoding="utf-8")
        self._git("add", "main.py")
        self._git("commit", "-m", "initial")
        self.workspace = WorkspaceService(self.workspace_root)
        self.service = GitService(self.workspace)

    def tearDown(self):
        self.temporary.cleanup()

    def _git(self, *arguments):
        return subprocess.run(
            ["/usr/bin/git", *arguments], cwd=self.root,
            check=True, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.workspace_root), "LANG": "C.UTF-8"},
        )

    def test_clean_modified_untracked_deleted_renamed_and_conflict_status(self):
        clean = self.service.status("project/main.py")
        self.assertTrue(clean["clean"])
        self.assertEqual(clean["branch"], "main")
        (self.root / "main.py").write_text("value = 2\n", encoding="utf-8")
        (self.root / "new.js").write_text("console.log('ok')\n", encoding="utf-8")
        status = self.service.status("project")
        self.assertEqual({item["kind"] for item in status["entries"]}, {"modified", "untracked"})
        (self.root / "main.py").unlink()
        self.assertEqual(next(item for item in self.service.status("project")["entries"] if item["path"] == "main.py")["kind"], "deleted")
        self._git("restore", "main.py")
        self._git("mv", "main.py", "renamed.py")
        renamed = self.service.status("project")
        self.assertTrue(any(item["kind"] == "renamed" and item["original_path"] == "main.py" for item in renamed["entries"]))

    def test_conflict_is_reported_without_exposing_restricted_files(self):
        self._git("switch", "-c", "other")
        (self.root / "main.py").write_text("other branch\n", encoding="utf-8")
        self._git("commit", "-am", "other")
        self._git("switch", "main")
        (self.root / "main.py").write_text("main branch\n", encoding="utf-8")
        self._git("commit", "-am", "main")
        subprocess.run(["/usr/bin/git", "merge", "other"], cwd=self.root, capture_output=True)
        (self.root / ".env").write_text("TOKEN=hidden", encoding="utf-8")
        result = self.service.status("project")
        self.assertEqual(result["conflicts"], 1)
        self.assertTrue(any(item["kind"] == "conflict" and item["path"] == "main.py" for item in result["entries"]))
        self.assertGreaterEqual(result["restricted"], 1)
        self.assertFalse(any(item["path"] == ".env" for item in result["entries"]))

    def test_stage_unstage_diff_and_commit_with_fixed_hook_policy(self):
        (self.root / "main.py").write_text("value = 2\n", encoding="utf-8")
        working = self.service.diff("project", "main.py")
        self.assertIn("+value = 2", working["diff"])
        status = self.service.stage("project", ["main.py"])
        self.assertTrue(next(item for item in status["entries"] if item["path"] == "main.py")["staged"])
        self.assertIn("+value = 2", self.service.diff("project", "main.py", True)["diff"])
        self.service.unstage("project", ["main.py"])
        self.assertFalse(next(item for item in self.service.status("project")["entries"] if item["path"] == "main.py")["staged"])
        self.service.stage("project", ["main.py"])
        marker = self.workspace_root / "hook-ran"
        hook = self.root / ".git/hooks/pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 9\n", encoding="utf-8")
        hook.chmod(0o755)
        preview = self.service.preview_commit("project", "safe local commit")
        result = self.service.apply_commit(preview["token"])
        self.assertRegex(result["hash"], r"^[0-9a-f]{12}$")
        self.assertEqual(result["message"], "safe local commit")
        self.assertFalse(marker.exists())

    def test_rename_stages_and_unstages_source_and_destination_together(self):
        self._git("mv", "main.py", "renamed.py")
        staged = self.service.stage("project", ["renamed.py"])
        rename = next(item for item in staged["entries"] if item["kind"] == "renamed")
        self.assertTrue(rename["staged"])
        unstaged = self.service.unstage("project", ["renamed.py"])
        self.assertTrue(any(item["path"] == "main.py" and item["kind"] == "deleted" for item in unstaged["entries"]))
        self.assertTrue(any(item["path"] == "renamed.py" and item["kind"] == "untracked" for item in unstaged["entries"]))

    def test_commit_rejects_sensitive_file_staged_outside_geram(self):
        (self.root / ".env").write_text("TOKEN=hidden\n", encoding="utf-8")
        self._git("add", "-f", ".env")
        result = self.service.status("project")
        self.assertEqual(result["restricted_staged"], 1)
        with self.assertRaisesRegex(WorkspaceError, "Protected staged"):
            self.service.preview_commit("project", "must not include secret")

    def test_empty_commit_invalid_messages_and_preview_conflict(self):
        with self.assertRaisesRegex(WorkspaceError, "no staged"):
            self.service.preview_commit("project", "empty")
        for message in ("", " leading", "trailing ", "bad\nmessage", "x" * 201):
            with self.subTest(message=message), self.assertRaises(WorkspaceError):
                self.service.preview_commit("project", message)
        (self.root / "main.py").write_text("value = 2\n", encoding="utf-8")
        self.service.stage("project", ["main.py"])
        preview = self.service.preview_commit("project", "first")
        (self.root / "other.py").write_text("x = 1\n", encoding="utf-8")
        self.service.stage("project", ["other.py"])
        with self.assertRaisesRegex(WorkspaceError, "staged changes changed"):
            self.service.apply_commit(preview["token"])

    def test_commit_preview_detects_changed_index_content_for_same_path(self):
        (self.root / "main.py").write_text("value = 2\n", encoding="utf-8")
        self.service.stage("project", ["main.py"])
        preview = self.service.preview_commit("project", "reviewed content")
        (self.root / "main.py").write_text("value = 3\n", encoding="utf-8")
        self._git("add", "main.py")
        with self.assertRaisesRegex(WorkspaceError, "staged changes changed"):
            self.service.apply_commit(preview["token"])

    def test_new_branch_safe_switch_and_dirty_switch_blocked(self):
        result = self.service.switch("project", "feature/safe", create=True)
        self.assertEqual(result["branch"], "feature/safe")
        branches = self.service.branches("project")["branches"]
        self.assertTrue(any(item == {"name": "feature/safe", "current": True} for item in branches))
        self.service.switch("project", "main")
        (self.root / "main.py").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "clean worktree"):
            self.service.switch("project", "feature/safe")
        for name in ("-force", "bad name", "../escape", "name.lock", "bad~name"):
            with self.subTest(name=name), self.assertRaises(WorkspaceError):
                self.service.switch("project", name, create=True)

    def test_discard_requires_preview_detects_conflict_and_restores_file(self):
        (self.root / "main.py").write_text("value = 2\n", encoding="utf-8")
        preview = self.service.preview_discard("project", "main.py")
        self.assertIn("+value = 2", preview["diff"])
        (self.root / "main.py").write_text("value = 3\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "changed before discard"):
            self.service.apply_discard(preview["token"])
        preview = self.service.preview_discard("project", "main.py")
        result = self.service.apply_discard(preview["token"])
        self.assertEqual(result["path"], "main.py")
        self.assertEqual((self.root / "main.py").read_text(), "value = 1\n")

    def test_paths_secrets_symlinks_hardlinks_and_repository_escape_fail_closed(self):
        outside = self.workspace_root.parent / "outside-source-control.txt"
        outside.write_text("secret", encoding="utf-8")
        (self.root / "link.py").symlink_to(outside)
        os.link(self.root / "main.py", self.root / "hard.py")
        (self.root / ".env").write_text("TOKEN=x", encoding="utf-8")
        try:
            for path in ("/tmp/x", "../x", "link.py", "hard.py", ".env"):
                with self.subTest(path=path), self.assertRaises(WorkspaceError):
                    self.service.stage("project", [path])
            external_repo = self.workspace_root.parent / "external-repo"
            external_repo.mkdir(exist_ok=True)
            subprocess.run(["/usr/bin/git", "init", "-q", str(external_repo)], check=True)
            with self.assertRaises(WorkspaceError):
                self.service.status(str(external_repo))
        finally:
            outside.unlink(missing_ok=True)
            if (self.workspace_root.parent / "external-repo").exists():
                import shutil
                shutil.rmtree(self.workspace_root.parent / "external-repo")

    def test_hostile_config_attributes_and_git_absence_are_rejected(self):
        with (self.root / ".git/config").open("a", encoding="utf-8") as handle:
            handle.write('\n[filter "evil"]\n\tclean = touch /tmp/evil\n')
        with self.assertRaisesRegex(WorkspaceError, "Executable Git configuration"):
            self.service.status("project")
        config = self.root / ".git/config"
        text = config.read_text()
        config.write_text(text.split('[filter "evil"]')[0], encoding="utf-8")
        (self.root / ".gitattributes").write_text("*.txt filter=evil\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "attributes"):
            self.service.status("project")
        (self.root / ".gitattributes").unlink()
        with self.assertRaisesRegex(WorkspaceError, "trusted Git"):
            GitService(self.workspace, self.root / "fake-git").status("project")

    def test_timeout_kills_git_process_group(self):
        class SlowProcess:
            pid = 999999
            returncode = None
            def communicate(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired("git", timeout)
                self.returncode = -9
                return b"", b""
        with patch("app.core.git_service.subprocess.Popen", return_value=SlowProcess()), patch("app.core.git_service.os.killpg") as kill:
            with self.assertRaisesRegex(WorkspaceError, "timed out"):
                self.service.status("project")
            kill.assert_called_once_with(999999, 9)


class SourceControlApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["/usr/bin/git", "init", "-q", "-b", "main", self.root], check=True)
        subprocess.run(["/usr/bin/git", "config", "user.name", "GERAM Test"], cwd=self.root, check=True)
        subprocess.run(["/usr/bin/git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        (self.root / "main.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["/usr/bin/git", "add", "main.py"], cwd=self.root, check=True)
        subprocess.run(["/usr/bin/git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        self.previous = source_control.service
        source_control.service = GitService(WorkspaceService(self.root))
        app.dependency_overrides[require_localhost] = lambda: None
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")
        self.headers = {"Origin": "http://127.0.0.1:8000"}

    def tearDown(self):
        source_control.service = self.previous
        app.dependency_overrides.pop(require_localhost, None)
        self.temporary.cleanup()

    def test_read_routes_and_mutations_have_closed_contracts(self):
        self.assertEqual(self.client.get("/api/source-control/status").status_code, 200)
        (self.root / "main.py").write_text("x = 2\n", encoding="utf-8")
        diff = self.client.get("/api/source-control/diff", params={"path": "main.py"})
        self.assertEqual(diff.status_code, 200)
        self.assertIn("+x = 2", diff.json()["diff"])
        external_origin = self.client.post("/api/source-control/stage", json={"paths": ["main.py"]}, headers={"Origin": "https://evil.invalid"})
        self.assertEqual(external_origin.status_code, 403)
        extra = self.client.post("/api/source-control/stage", json={"paths": ["main.py"], "command": "push"}, headers=self.headers)
        self.assertEqual(extra.status_code, 422)
        staged = self.client.post("/api/source-control/stage", json={"paths": ["main.py"]}, headers=self.headers)
        self.assertEqual(staged.status_code, 200)
        self.assertTrue(staged.json()["entries"][0]["staged"])


if __name__ == "__main__":
    unittest.main()
