import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.sandbox_backend import (
    SandboxBackend,
    SandboxUnavailableError,
    build_sandbox_prefix,
    detect_sandbox_backend,
    is_enforced_sandbox_prefix,
)

class SandboxBackendTests(unittest.TestCase):
    def test_bubblewrap_available_and_prefix_is_closed(self):
        backend = detect_sandbox_backend()
        with tempfile.TemporaryDirectory() as root:
            prefix = build_sandbox_prefix(backend, Path(root), Path(root))
        self.assertEqual(backend.name, "bubblewrap")
        self.assertIn("--unshare-all", prefix)
        self.assertIn("--unshare-user", prefix)
        self.assertIn("--disable-userns", prefix)
        self.assertIn("--clearenv", prefix)
        self.assertIn("--tmpfs", prefix)
        self.assertIn("/workspace", prefix)
        self.assertNotIn("--share-net", prefix)
        self.assertEqual(prefix[-1], "--")
        self.assertTrue(is_enforced_sandbox_prefix(prefix))

    def test_sensitive_workspace_entries_are_overlaid(self):
        backend = detect_sandbox_backend()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("synthetic", encoding="utf-8")
            os.link(root / ".env", root / "env-hardlink.txt")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("synthetic", encoding="utf-8")
            (root / "state.sqlite3").write_text("synthetic", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / ".env.local").write_text("synthetic", encoding="utf-8")
            prefix = build_sandbox_prefix(backend, root, root)

        for destination in (
            "/workspace/.env",
            "/workspace/env-hardlink.txt",
            "/workspace/state.sqlite3",
            "/workspace/nested/.env.local",
        ):
            index = prefix.index(destination)
            self.assertEqual(prefix[index - 2:index], ["--ro-bind", "/dev/null"])
        git_index = prefix.index("/workspace/.git")
        self.assertEqual(prefix[git_index - 1], "--tmpfs")
        self.assertIn(
            ["--remount-ro", "/workspace/.git"],
            [prefix[index:index + 2] for index in range(len(prefix) - 1)],
        )

    def test_path_lookup_cannot_replace_bubblewrap_and_invalid_backend_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary) / "bwrap"
            fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            with patch.dict(os.environ, {"PATH": temporary}):
                backend = detect_sandbox_backend()
            self.assertNotEqual(Path(backend.executable), fake)
            with self.assertRaises(SandboxUnavailableError):
                build_sandbox_prefix(
                    SandboxBackend("bubblewrap", str(fake)),
                    Path(temporary),
                    Path(temporary),
                )
        self.assertFalse(is_enforced_sandbox_prefix([]))
