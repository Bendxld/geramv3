import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.workspace import WorkspaceError, WorkspaceService
from app.core.workspace_operations import WorkspaceOperations


class WorkspaceOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "dest").mkdir()
        (self.root / "src/main.py").write_text("value = 1\n", encoding="utf-8")
        self.workspace = WorkspaceService(self.root)
        self.operations = WorkspaceOperations(self.workspace)

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_file_folder_and_nested_file(self):
        folder = self.operations.create("", "project", "directory")
        first = self.operations.create("project", "main.py", "file")
        second = self.operations.create("src", "util.js", "file")
        self.assertEqual(folder, {"path": "project", "type": "directory"})
        self.assertEqual(first["path"], "project/main.py")
        self.assertEqual(second["path"], "src/util.js")
        self.assertTrue((self.root / "project/main.py").is_file())

    def test_rename_file_and_nonempty_folder_is_atomic(self):
        preview = self.operations.preview_move("src/main.py", "src", "renamed.py")
        self.assertEqual(preview["destination"], "src/renamed.py")
        result = self.operations.apply_move(preview["token"])
        self.assertEqual(result["old_path"], "src/main.py")
        self.assertEqual(result["new_path"], "src/renamed.py")
        folder = self.operations.preview_move("src", "", "source")
        result = self.operations.apply_move(folder["token"])
        self.assertTrue((self.root / "source/renamed.py").is_file())
        self.assertIn("src/renamed.py", result["affected"])

    def test_move_rejects_collision_and_circular_destination(self):
        (self.root / "dest/main.py").write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "already exists"):
            self.operations.preview_move("src/main.py", "dest")
        self.assertTrue((self.root / "src/main.py").is_file())
        (self.root / "src/child").mkdir()
        with self.assertRaisesRegex(WorkspaceError, "inside itself"):
            self.operations.preview_move("src", "src/child")

    def test_duplicate_suggested_name_and_collision(self):
        result = self.operations.duplicate("src/main.py", "main copy.py")
        self.assertEqual((self.root / result["path"]).read_text(), "value = 1\n")
        with self.assertRaisesRegex(WorkspaceError, "already exists"):
            self.operations.duplicate("src/main.py", "main copy.py")

    def test_delete_file_and_nonempty_directory_require_preview(self):
        file_preview = self.operations.preview_delete("src/main.py")
        self.assertTrue((self.root / "src/main.py").exists())
        self.operations.apply_delete(file_preview["token"])
        self.assertFalse((self.root / "src/main.py").exists())
        (self.root / "src/a").mkdir()
        (self.root / "src/a/test.js").write_text("x", encoding="utf-8")
        preview = self.operations.preview_delete("src")
        self.assertEqual(preview["count"], 3)
        result = self.operations.apply_delete(preview["token"])
        self.assertFalse((self.root / "src").exists())
        self.assertFalse(result["cleanup_pending"])

    def test_absolute_traversal_sensitive_and_root_are_rejected(self):
        for action in (
            lambda: self.operations.create("../outside", "x.py", "file"),
            lambda: self.operations.create("", "/tmp/x", "file"),
            lambda: self.operations.preview_delete("/tmp/x"),
            lambda: self.operations.preview_delete(".git"),
            lambda: self.operations.preview_delete(""),
        ):
            with self.subTest(action=action), self.assertRaises(WorkspaceError):
                action()

    def test_symlink_and_hardlink_are_rejected_for_every_destructive_operation(self):
        outside = self.root.parent / "outside-operations.py"
        outside.write_text("secret", encoding="utf-8")
        (self.root / "external.py").symlink_to(outside)
        os.link(self.root / "src/main.py", self.root / "hard.py")
        try:
            for path in ("external.py", "hard.py"):
                with self.subTest(path=path), self.assertRaises(WorkspaceError):
                    self.operations.preview_delete(path)
                with self.subTest(path=path), self.assertRaises(WorkspaceError):
                    self.operations.preview_move(path, "dest")
        finally:
            outside.unlink(missing_ok=True)

    def test_folder_with_symlink_or_hardlink_fails_before_mutation(self):
        outside = self.root.parent / "outside-folder.py"
        outside.write_text("secret", encoding="utf-8")
        (self.root / "src/external.py").symlink_to(outside)
        try:
            with self.assertRaises(WorkspaceError):
                self.operations.preview_delete("src")
            self.assertTrue((self.root / "src").exists())
        finally:
            outside.unlink(missing_ok=True)

    def test_rename_failure_rolls_back_by_leaving_source_unchanged(self):
        preview = self.operations.preview_move("src/main.py", "dest")
        with patch("app.core.workspace_operations._rename_noreplace", side_effect=WorkspaceError("operation_failed", "failed", 409)):
            with self.assertRaises(WorkspaceError):
                self.operations.apply_move(preview["token"])
        self.assertTrue((self.root / "src/main.py").is_file())
        self.assertFalse((self.root / "dest/main.py").exists())

    def test_preview_conflict_detects_identity_change(self):
        preview = self.operations.preview_delete("src/main.py")
        (self.root / "src/main.py").unlink()
        (self.root / "src/main.py").write_text("replacement", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "changed"):
            self.operations.apply_delete(preview["token"])
        self.assertTrue((self.root / "src/main.py").exists())


if __name__ == "__main__":
    unittest.main()
