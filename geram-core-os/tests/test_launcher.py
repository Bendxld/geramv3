"""Regression tests for identity-safe GERAM CORE OS process launching."""

import os
import secrets
import signal
import stat
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import launcher as launcher_module

from launcher import (
    BackendLauncher,
    CANONICAL_ENTRYPOINT,
    LOCAL_HOST,
    LauncherError,
    PidRecord,
    ProcessSnapshot,
    configured_port,
    resolve_project_root,
    validate_project_root,
)


class FakeInspector:
    def __init__(self):
        self.snapshots: dict[int, ProcessSnapshot] = {}
        self.listeners: set[int] = set()

    def snapshot(self, pid: int):
        return self.snapshots.get(pid)

    def iter_snapshots(self):
        return iter(list(self.snapshots.values()))

    def owns_listener(self, pid: int, host: str, port: int) -> bool:
        return host == LOCAL_HOST and pid in self.listeners


class LauncherTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        temporary_root = Path(self.temporary_directory.name)
        self.root = temporary_root / "GERAM Core OS with spaces"
        (self.root / "app").mkdir(parents=True)
        (self.root / "static").mkdir()
        (self.root / "venv/bin").mkdir(parents=True)
        (self.root / "app/__init__.py").write_text("")
        (self.root / "app/main.py").write_text("app = object()\n")
        (self.root / "static/index.html").write_text("<html></html>\n")
        (self.root / "requirements.txt").write_text("uvicorn\n")
        (self.root / "server.py").write_text("# unrelated legacy name\n")
        (self.root / "venv/bin/python").write_text("#!/bin/sh\n")
        (self.root / "venv/bin/python").chmod(0o755)
        self.state_dir = temporary_root / "private launcher state"
        self.inspector = FakeInspector()
        self.spawn_calls: list[tuple[list[str], dict[str, object]]] = []
        self.next_pid = 43210

    def make_launcher(self, *, port=18080, lifespan_off=False):
        def fake_popen(command, **kwargs):
            self.spawn_calls.append((list(command), kwargs))
            snapshot = ProcessSnapshot(
                pid=self.next_pid,
                start_ticks=987654,
                executable=(self.root / "venv/bin/python").resolve(),
                cwd=self.root.resolve(),
                argv=tuple(command),
            )
            self.inspector.snapshots[self.next_pid] = snapshot
            self.inspector.listeners.add(self.next_pid)
            return SimpleNamespace(pid=self.next_pid)

        instance = BackendLauncher(
            self.root,
            port=port,
            state_dir=self.state_dir,
            lifespan_off=lifespan_off,
            inspector=self.inspector,
            popen=fake_popen,
        )
        self.addCleanup(self.inspector.snapshots.clear)
        self.addCleanup(self.inspector.listeners.clear)
        return instance

    def managed_snapshot(self, instance, pid=43210, start_ticks=987654):
        return ProcessSnapshot(
            pid=pid,
            start_ticks=start_ticks,
            executable=instance.python.resolve(),
            cwd=instance.root,
            argv=tuple(instance.command()),
        )

    def legacy_snapshot(self, instance, pid=54321, start_ticks=123456):
        return ProcessSnapshot(
            pid=pid,
            start_ticks=start_ticks,
            executable=instance.python.resolve(),
            cwd=instance.root,
            argv=(str(instance.python), "server.py"),
        )

    def manual_snapshot(self, instance, pid=65432, start_ticks=234567):
        return ProcessSnapshot(
            pid=pid,
            start_ticks=start_ticks,
            executable=instance.python.resolve(),
            cwd=instance.root,
            argv=("python", "-m", "app.main"),
        )

    def write_record(self, instance, snapshot, *, kind="managed"):
        record = PidRecord(
            pid=snapshot.pid,
            start_ticks=snapshot.start_ticks,
            root=str(instance.root),
            entrypoint=CANONICAL_ENTRYPOINT,
            host=LOCAL_HOST,
            port=instance.port,
            kind=kind,
            lifespan_off=instance.lifespan_off if kind == "managed" else False,
        )
        instance._write_pid_record(record)
        return record


class ProjectResolutionTests(LauncherTestCase):
    def test_launcher_selects_core_even_with_other_server_files(self):
        legacy_root = Path(self.temporary_directory.name) / "legacy"
        legacy_root.mkdir()
        (legacy_root / "server.py").write_text("# legacy server\n")
        launcher_path = self.root / "launcher.py"

        previous_cwd = Path.cwd()
        try:
            os.chdir(legacy_root)
            resolved = resolve_project_root(launcher_path)
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(resolved, self.root.resolve())
        self.assertTrue((legacy_root / "server.py").is_file())

    def test_missing_entrypoint_is_a_controlled_error(self):
        (self.root / "app/main.py").unlink()
        with self.assertRaises(LauncherError) as raised:
            validate_project_root(self.root)
        self.assertIn("entrypoint", str(raised.exception))

    def test_paths_with_spaces_remain_single_process_arguments(self):
        instance = self.make_launcher()
        with (
            patch.object(instance, "_port_in_use", return_value=False),
            patch.object(instance, "_health_ok", return_value=True),
        ):
            outcome = instance.start(timeout=0.1)
        command, options = self.spawn_calls[0]
        self.assertEqual(outcome.action, "started")
        self.assertEqual(command[0], str(self.root / "venv/bin/python"))
        self.assertEqual(options["cwd"], self.root.resolve())
        self.assertNotIn("server.py", command)


class ProcessIdentityTests(LauncherTestCase):
    def test_foreign_process_on_port_is_not_identified_or_stopped(self):
        instance = self.make_launcher()
        foreign = self.legacy_snapshot(instance)
        self.inspector.snapshots[foreign.pid] = foreign
        kill_calls = []
        with (
            patch.object(instance, "_port_in_use", return_value=True),
            patch.object(launcher_module.os, "kill", side_effect=lambda *args: kill_calls.append(args)),
        ):
            with self.assertRaises(LauncherError) as raised:
                instance.start(timeout=0)
        self.assertIn("ocupado", str(raised.exception))
        self.assertEqual(kill_calls, [])
        self.assertEqual(self.spawn_calls, [])

    def test_stale_pid_does_not_kill_reused_foreign_pid(self):
        instance = self.make_launcher()
        previous = self.managed_snapshot(instance, pid=22222, start_ticks=100)
        self.write_record(instance, previous)
        reused = self.legacy_snapshot(instance, pid=22222, start_ticks=200)
        self.inspector.snapshots[reused.pid] = reused
        kill_calls = []
        with (
            patch.object(instance, "_port_in_use", return_value=True),
            patch.object(launcher_module.os, "kill", side_effect=lambda *args: kill_calls.append(args)),
        ):
            with self.assertRaises(LauncherError):
                instance.start(timeout=0)
        self.assertEqual(kill_calls, [])
        self.assertFalse(instance.pid_file.exists())

    def test_legitimate_process_is_recognized_and_not_duplicated(self):
        instance = self.make_launcher()
        legitimate = self.managed_snapshot(instance)
        self.inspector.snapshots[legitimate.pid] = legitimate
        self.inspector.listeners.add(legitimate.pid)
        with patch.object(instance, "_health_ok", return_value=True):
            first = instance.start(timeout=0.1)
            second = instance.start(timeout=0.1)
        self.assertEqual(first.action, "already_running")
        self.assertEqual(second.action, "already_running")
        self.assertEqual(self.spawn_calls, [])
        self.assertEqual(stat.S_IMODE(instance.pid_file.stat().st_mode), 0o600)

    def test_existing_manual_module_process_is_recognized(self):
        instance = self.make_launcher()
        legitimate = self.manual_snapshot(instance)
        self.inspector.snapshots[legitimate.pid] = legitimate
        self.inspector.listeners.add(legitimate.pid)
        with patch.object(instance, "_health_ok", return_value=True):
            outcome = instance.start(timeout=0.1)
        self.assertEqual(outcome.action, "already_running")
        self.assertEqual(outcome.pid, legitimate.pid)
        self.assertEqual(self.spawn_calls, [])

    def test_smoke_mode_does_not_adopt_manual_core_on_another_port(self):
        instance = self.make_launcher(lifespan_off=True)
        other_port_process = self.manual_snapshot(instance)
        self.inspector.snapshots[other_port_process.pid] = other_port_process
        with (
            patch.object(instance, "_port_in_use", return_value=False),
            patch.object(instance, "_health_ok", return_value=True),
        ):
            outcome = instance.start(timeout=0.1)
        self.assertEqual(outcome.action, "started")
        self.assertEqual(len(self.spawn_calls), 1)

    def test_legacy_server_is_neither_started_nor_stopped(self):
        instance = self.make_launcher()
        legacy = self.legacy_snapshot(instance)
        self.inspector.snapshots[legacy.pid] = legacy
        kill_calls = []
        with patch.object(launcher_module.os, "kill", side_effect=lambda *args: kill_calls.append(args)):
            stopped = instance.stop(timeout=0)
        self.assertEqual(stopped.action, "not_running")
        self.assertEqual(kill_calls, [])
        self.assertEqual(self.spawn_calls, [])

    def test_stop_revalidates_identity_and_cleans_pid_file(self):
        instance = self.make_launcher()
        legitimate = self.managed_snapshot(instance)
        self.inspector.snapshots[legitimate.pid] = legitimate
        self.inspector.listeners.add(legitimate.pid)
        self.write_record(instance, legitimate)
        signals = []

        def terminate(pid, selected_signal):
            signals.append((pid, selected_signal))
            self.inspector.snapshots.pop(pid, None)
            self.inspector.listeners.discard(pid)

        with patch.object(launcher_module.os, "kill", side_effect=terminate):
            outcome = instance.stop(timeout=0.1)
        self.assertEqual(outcome.action, "stopped")
        self.assertEqual(signals, [(legitimate.pid, signal.SIGTERM)])
        self.assertFalse(instance.pid_file.exists())
        self.assertEqual(list(self.state_dir.glob("*.tmp")), [])

    def test_stop_refuses_foreign_process_referenced_by_pid_file(self):
        instance = self.make_launcher()
        old = self.managed_snapshot(instance, pid=33333, start_ticks=10)
        self.write_record(instance, old)
        foreign = self.legacy_snapshot(instance, pid=33333, start_ticks=11)
        self.inspector.snapshots[foreign.pid] = foreign
        kill_calls = []
        with patch.object(launcher_module.os, "kill", side_effect=lambda *args: kill_calls.append(args)):
            with self.assertRaises(LauncherError) as raised:
                instance.stop(timeout=0)
        self.assertIn("no pertenece", str(raised.exception))
        self.assertEqual(kill_calls, [])
        self.assertFalse(instance.pid_file.exists())


class LauncherSafetyTests(LauncherTestCase):
    def test_host_is_loopback_and_worker_count_is_exactly_one(self):
        instance = self.make_launcher()
        command = instance.command()
        self.assertEqual(instance.host, "127.0.0.1")
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--workers") + 1], "1")
        self.assertEqual(command.count("--workers"), 1)

    def test_error_messages_do_not_echo_sensitive_input(self):
        synthetic_sensitive_value = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {"APP_PORT": synthetic_sensitive_value}):
            with self.assertRaises(LauncherError) as raised:
                configured_port(self.root)
        self.assertNotIn(synthetic_sensitive_value, str(raised.exception))

    def test_health_requires_the_expected_bounded_json_contract(self):
        instance = self.make_launcher()

        class Response:
            def __init__(self, status, body):
                self.status = status
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit):
                return self.body

        class Opener:
            def __init__(self, response):
                self.response = response

            def open(self, _url, timeout):
                self.timeout = timeout
                return self.response

        cases = (
            (Response(200, b'{"status":"ok"}'), True),
            (Response(200, b'{"status":"legacy"}'), False),
            (Response(200, b'not-json'), False),
            (Response(503, b'{"status":"ok"}'), False),
            (Response(200, b'x' * 1025), False),
        )
        for response, expected in cases:
            with self.subTest(status=response.status, size=len(response.body)):
                with patch.object(
                    launcher_module.urllib.request,
                    "build_opener",
                    return_value=Opener(response),
                ):
                    self.assertEqual(instance._health_ok(), expected)

    def test_pid_file_contains_only_operational_identity(self):
        instance = self.make_launcher()
        snapshot = self.managed_snapshot(instance)
        self.write_record(instance, snapshot)
        payload = instance.pid_file.read_text(encoding="utf-8")
        forbidden_names = ("secret", "token", "credential", "api_key", "environment")
        self.assertTrue(all(name not in payload.lower() for name in forbidden_names))
        self.assertEqual(stat.S_IMODE(instance.pid_file.stat().st_mode), 0o600)

    def test_scripts_and_restart_delegate_without_weak_process_matching(self):
        repository_root = Path(__file__).resolve().parent.parent
        for name in ("iniciar_app.sh", "iniciar_kiosk.sh"):
            source = (repository_root / name).read_text(encoding="utf-8")
            self.assertIn("launcher.py", source)
            self.assertNotIn("python -m app.main", source)
            self.assertNotIn("curl -s -o /dev/null", source)

        restart_source = (repository_root / "app/api/config.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("LAUNCHER_PATH", restart_source)
        self.assertNotIn("kill -TERM", restart_source)
        self.assertNotIn("pkill", restart_source)
        self.assertNotIn("fuser", restart_source)


if __name__ == "__main__":
    unittest.main()
