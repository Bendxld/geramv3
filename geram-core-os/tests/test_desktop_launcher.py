"""Tests for the Linux desktop lifecycle wrapper."""

import fcntl
import os
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from desktop_launcher import (
    DesktopLauncher,
    DesktopLauncherError,
    ElectronRecord,
    _electron_environment,
)
from launcher import LaunchOutcome


class FakeBackend:
    def __init__(self, action="started"):
        self.action = action
        self.start_calls = 0
        self.stop_calls = 0

    def start(self, timeout):
        self.start_calls += 1
        return LaunchOutcome(self.action, 12345)

    def stop(self, timeout):
        self.stop_calls += 1
        return LaunchOutcome("stopped", 12345)


class FakeElectron:
    def __init__(self, pid=54321, return_code=0):
        self.pid = pid
        self.return_code = return_code

    def wait(self, timeout=None):
        return self.return_code

    def poll(self):
        return self.return_code


class DesktopLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "GERAM CORE OS"
        (self.root / "app").mkdir(parents=True)
        (self.root / "static").mkdir()
        (self.root / "electron/node_modules/electron/dist").mkdir(parents=True)
        (self.root / "app/__init__.py").write_text("")
        (self.root / "app/main.py").write_text("app = object()\n")
        (self.root / "static/index.html").write_text("<html></html>\n")
        (self.root / "requirements.txt").write_text("uvicorn\n")
        (self.root / "electron/main.js").write_text("// electron\n")
        binary = self.root / "electron/node_modules/electron/dist/electron"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        self.backend = FakeBackend()
        self.electron = FakeElectron()
        self.notifications = []

    def make_launcher(self, *, backend_action="started", uid=1000):
        self.backend = FakeBackend(backend_action)

        def backend_factory(*_args, **_kwargs):
            return self.backend

        return DesktopLauncher(
            self.root,
            port=18080,
            backend_factory=backend_factory,
            popen=lambda *_args, **_kwargs: self.electron,
            notifier=lambda message, **kwargs: self.notifications.append((message, kwargs)),
            geteuid=lambda: uid,
        )

    @staticmethod
    def identity(launcher, *, backend_owned=False):
        return ElectronRecord(
            pid=54321,
            start_ticks=987654,
            root=str(launcher.root),
            port=launcher.port,
            backend_owned=backend_owned,
            lifespan_off=False,
        )

    def test_owned_backend_is_stopped_after_electron_closes(self):
        launcher = self.make_launcher()
        with patch.object(launcher, "_wait_for_identity", return_value=self.identity(launcher)):
            result = launcher.run()
        self.assertEqual(result, 0)
        self.assertEqual(self.backend.start_calls, 1)
        self.assertEqual(self.backend.stop_calls, 1)
        self.assertFalse(launcher.pid_file.exists())
        self.assertEqual(list(self.root.glob("..electron_app.pid.*")), [])

    def test_preexisting_backend_is_not_stopped(self):
        launcher = self.make_launcher(backend_action="already_running")
        with patch.object(launcher, "_wait_for_identity", return_value=self.identity(launcher)):
            self.assertEqual(launcher.run(), 0)
        self.assertEqual(self.backend.start_calls, 1)
        self.assertEqual(self.backend.stop_calls, 0)

    def test_second_desktop_launch_is_serialized_without_spawn(self):
        launcher = self.make_launcher()
        descriptor = os.open(launcher.lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(launcher.run(), 0)
        self.assertEqual(self.backend.start_calls, 0)
        self.assertIn("ya está abierto", self.notifications[0][0])

    def test_malformed_legacy_pid_is_removed_without_signal(self):
        launcher = self.make_launcher()
        launcher.pid_file.write_text("51826\n")
        with (
            patch.object(launcher, "_wait_for_identity", return_value=self.identity(launcher)),
            patch("desktop_launcher.os.kill") as kill,
        ):
            self.assertEqual(launcher.run(), 0)
        kill.assert_not_called()
        self.assertFalse(launcher.pid_file.exists())

    def test_root_and_missing_electron_fail_before_backend_start(self):
        root_launcher = self.make_launcher(uid=0)
        with self.assertRaisesRegex(DesktopLauncherError, "root"):
            root_launcher.run()
        self.assertEqual(self.backend.start_calls, 0)

        launcher = self.make_launcher()
        launcher.electron_binary.unlink()
        with self.assertRaisesRegex(DesktopLauncherError, "Electron"):
            launcher.run()
        self.assertEqual(self.backend.start_calls, 0)

    def test_electron_environment_is_allowlisted(self):
        environment = _electron_environment(18080, {
            "HOME": "/tmp/synthetic-home",
            "DISPLAY": ":99",
            "OPENAI_API_KEY": "synthetic-secret",
            "HTTP_PROXY": "http://synthetic.invalid",
            "PATH": "/untrusted",
        })
        self.assertEqual(environment["HOME"], "/tmp/synthetic-home")
        self.assertEqual(environment["DISPLAY"], ":99")
        self.assertEqual(environment["PATH"], "/usr/bin:/bin")
        self.assertEqual(environment["GERAM_ELECTRON_PORT"], "18080")
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("HTTP_PROXY", environment)

    def test_log_rejects_unstructured_or_sensitive_detail(self):
        launcher = self.make_launcher()
        launcher._log("TOKEN=synthetic-secret!")
        content = launcher.log_file.read_text()
        self.assertIn("invalid_log_event", content)
        self.assertNotIn("synthetic-secret", content)

    def test_stop_never_signals_an_unvalidated_pid(self):
        launcher = self.make_launcher()
        launcher._write_record(self.identity(launcher))
        with (
            patch.object(launcher, "_validate_electron", return_value=False),
            patch("desktop_launcher.os.kill") as kill,
        ):
            self.assertEqual(launcher.stop(), 0)
        kill.assert_not_called()
        self.assertFalse(launcher.pid_file.exists())

    def test_identity_accepts_only_exact_original_or_electron_process_title(self):
        launcher = self.make_launcher()
        record = self.identity(launcher)
        command = os.fsencode(str(launcher.electron_binary))
        application = os.fsencode(str(launcher.electron_app))

        class ProcFile:
            def __init__(self, data):
                self.data = data

            def resolve(self, strict=True):
                return self.data

            def read_bytes(self):
                return self.data

        class ProcPath:
            def __init__(self, argv):
                self.argv = argv

            def __truediv__(self, name):
                values = {
                    "exe": ProcFile(launcher.electron_binary),
                    "cwd": ProcFile(launcher.root),
                    "cmdline": ProcFile(self.argv),
                }
                return values[name]

        representations = (
            command + b"\0" + application + b"\0",
            command + b" " + application + b"\0",
        )
        for argv in representations:
            with self.subTest(argv=argv):
                with (
                    patch("desktop_launcher._process_start_ticks", return_value=record.start_ticks),
                    patch("desktop_launcher.Path", return_value=ProcPath(argv)),
                ):
                    self.assertTrue(launcher._validate_electron(record))

        with (
            patch("desktop_launcher._process_start_ticks", return_value=record.start_ticks),
            patch("desktop_launcher.Path", return_value=ProcPath(command + b" --other\0")),
        ):
            self.assertFalse(launcher._validate_electron(record))


if __name__ == "__main__":
    unittest.main()
