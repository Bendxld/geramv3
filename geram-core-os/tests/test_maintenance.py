import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.core.maintenance import (
    MaintenanceError,
    create_backup,
    diagnostics,
    list_backups,
    restore_backup,
)
from scripts.release_artifacts import verify_checksums, write_checksums


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.workspace = tempfile.TemporaryDirectory()
        self.patch_data = patch.object(settings, "LOCAL_DATA_DIR", Path(self.data.name))
        self.patch_workspace = patch.object(settings, "WORKSPACE_ROOT", Path(self.workspace.name))
        self.patch_data.start(); self.patch_workspace.start()

    def tearDown(self):
        self.patch_workspace.stop(); self.patch_data.stop()
        self.workspace.cleanup(); self.data.cleanup()

    def test_backup_excludes_credentials_and_restore_creates_safety_copy(self):
        runtime = Path(self.data.name) / "runtime" / "preferences.json"
        runtime.parent.mkdir(parents=True)
        runtime.write_text('{"offline_forced":false}\n', encoding="utf-8")
        secret = Path(self.data.name) / "credentials" / "credential_pool.sqlite3"
        secret.parent.mkdir(parents=True)
        secret.write_bytes(b"secret-database")

        created = create_backup()
        archive_path = Path(self.data.name) / "backups" / created["id"]
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("runtime/preferences.json", archive.namelist())
            self.assertNotIn("credentials/credential_pool.sqlite3", archive.namelist())
        runtime.write_text('{"offline_forced":true}\n', encoding="utf-8")
        restored = restore_backup(created["id"])
        self.assertIn('false', runtime.read_text(encoding="utf-8"))
        self.assertTrue(restored["safety_backup"].endswith(".zip"))
        self.assertGreaterEqual(len(list_backups()), 2)

    def test_tampered_backup_is_rejected_before_writing(self):
        state = Path(self.data.name) / "agents" / "roster-state.json"
        state.parent.mkdir(parents=True)
        state.write_text('{"disabled":[]}\n', encoding="utf-8")
        created = create_backup()
        archive_path = Path(self.data.name) / "backups" / created["id"]
        with zipfile.ZipFile(archive_path, "r") as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["agents/roster-state.json"] = b"tampered"
        replacement = archive_path.with_suffix(".replacement")
        with zipfile.ZipFile(replacement, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        replacement.replace(archive_path)
        with self.assertRaises(MaintenanceError):
            restore_backup(created["id"])

    def test_diagnostics_are_path_and_secret_free(self):
        payload = diagnostics()
        rendered = json.dumps(payload)
        self.assertNotIn(self.data.name, rendered)
        self.assertFalse(payload["secrets_included"])


class ReleaseArtifactTests(unittest.TestCase):
    def test_checksums_are_deterministic_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "GERAM.exe").write_bytes(b"windows")
            (root / "GERAM.AppImage").write_bytes(b"linux")
            first = write_checksums(root).read_text(encoding="ascii")
            second = write_checksums(root).read_text(encoding="ascii")
            self.assertEqual(first, second)
            verify_checksums(root)
            (root / "GERAM.exe").write_bytes(b"changed")
            with self.assertRaises(RuntimeError):
                verify_checksums(root)
