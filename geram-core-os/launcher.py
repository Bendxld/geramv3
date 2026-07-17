#!/usr/bin/env python3
"""Identity-safe local process launcher for GERAM CORE OS.

The launcher never identifies a backend by port or a partial process-name
match. It combines a validated project root, exact argv, resolved executable,
working directory, PID start time, and listener ownership before reusing or
stopping a process.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator


CANONICAL_ENTRYPOINT = "app.main:app"
CANONICAL_MODULE = "app.main"
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PID_FILE_NAME = ".geram_core_os_backend.pid"
LOCK_FILE_NAME = ".geram_core_os_backend.pid.lock"
BACKEND_LOG_NAME = "geram_core_os.log"
MAX_PID_FILE_BYTES = 4096
PROJECT_MARKERS = (
    "app/__init__.py",
    "static/index.html",
    "requirements.txt",
)


class LauncherError(RuntimeError):
    """A sanitized launcher failure safe to display to a local user."""


@dataclass(frozen=True)
class ProcessSnapshot:
    pid: int
    start_ticks: int
    executable: Path
    cwd: Path
    argv: tuple[str, ...]


@dataclass(frozen=True)
class PidRecord:
    pid: int
    start_ticks: int
    root: str
    entrypoint: str
    host: str
    port: int
    kind: str
    lifespan_off: bool = False


@dataclass(frozen=True)
class LaunchOutcome:
    action: str
    pid: int | None = None
    warnings: tuple[str, ...] = ()


def validate_project_root(root: Path) -> Path:
    """Validate characteristic Core files without consulting the current cwd."""
    resolved = root.expanduser().resolve()
    for marker in PROJECT_MARKERS:
        if not (resolved / marker).is_file():
            raise LauncherError(
                "No se encontró una raíz válida de GERAM CORE OS."
            )
    if not (resolved / "app/main.py").is_file():
        raise LauncherError(
            "Falta el entrypoint canónico de GERAM CORE OS: app/main.py."
        )
    return resolved


def resolve_project_root(launcher_path: Path | None = None) -> Path:
    """Resolve the project from this launcher's real location."""
    source = (launcher_path or Path(__file__)).expanduser().resolve()
    return validate_project_root(source.parent)


def configured_port(root: Path) -> int:
    """Read only APP_PORT from local configuration without exposing values."""
    candidate: str | None = None
    env_path = root / ".env"
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                if key.strip() == "APP_PORT":
                    candidate = value.split("#", 1)[0].strip().strip("'\"")
                    break
        except OSError:
            raise LauncherError(
                "No se pudo leer la configuración local del puerto."
            ) from None
    if candidate is None:
        candidate = os.environ.get("APP_PORT", str(DEFAULT_PORT))
    try:
        port = int(candidate)
    except (TypeError, ValueError):
        raise LauncherError("APP_PORT debe ser un puerto local válido.") from None
    if not 1 <= port <= 65535:
        raise LauncherError("APP_PORT debe ser un puerto local válido.")
    return port


class ProcInspector:
    """Read Linux process and socket identity without logging command lines."""

    def __init__(self, proc_root: Path = Path("/proc")):
        self.proc_root = proc_root

    def snapshot(self, pid: int) -> ProcessSnapshot | None:
        if pid <= 1:
            return None
        process_dir = self.proc_root / str(pid)
        try:
            raw_stat = (process_dir / "stat").read_text(encoding="utf-8")
            stat_fields = raw_stat.rsplit(")", 1)[1].strip().split()
            start_ticks = int(stat_fields[19])
            executable = (process_dir / "exe").resolve(strict=True)
            cwd = (process_dir / "cwd").resolve(strict=True)
            raw_argv = (process_dir / "cmdline").read_bytes().split(b"\0")
            argv = tuple(
                part.decode("utf-8", errors="surrogateescape")
                for part in raw_argv
                if part
            )
        except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
            return None
        if not argv:
            return None
        return ProcessSnapshot(
            pid=pid,
            start_ticks=start_ticks,
            executable=executable,
            cwd=cwd,
            argv=argv,
        )

    def iter_snapshots(self) -> Iterator[ProcessSnapshot]:
        try:
            entries = list(self.proc_root.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.name.isdigit():
                continue
            snapshot = self.snapshot(int(entry.name))
            if snapshot is not None:
                yield snapshot

    def _ppid(self, pid: int) -> int | None:
        try:
            raw_stat = (self.proc_root / str(pid) / "stat").read_text(
                encoding="utf-8"
            )
            fields = raw_stat.rsplit(")", 1)[1].strip().split()
            return int(fields[1])
        except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
            return None

    def _process_tree(self, root_pid: int) -> set[int]:
        descendants = {root_pid}
        changed = True
        while changed:
            changed = False
            try:
                entries = list(self.proc_root.iterdir())
            except OSError:
                break
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                pid = int(entry.name)
                if pid in descendants:
                    continue
                if self._ppid(pid) in descendants:
                    descendants.add(pid)
                    changed = True
        return descendants

    def _listener_inodes(self, host: str, port: int) -> set[str]:
        if host != LOCAL_HOST:
            return set()
        address_hex = socket.inet_aton(host)[::-1].hex().upper()
        endpoint = f"{address_hex}:{port:04X}"
        inodes: set[str] = set()
        for table_name in ("net/tcp", "net/tcp6"):
            table = self.proc_root / table_name
            try:
                lines = table.read_text(encoding="utf-8").splitlines()[1:]
            except (FileNotFoundError, PermissionError, OSError):
                continue
            for line in lines:
                fields = line.split()
                if len(fields) > 9 and fields[1] == endpoint and fields[3] == "0A":
                    inodes.add(fields[9])
        return inodes

    def owns_listener(self, pid: int, host: str, port: int) -> bool:
        inodes = self._listener_inodes(host, port)
        if not inodes:
            return False
        for process_pid in self._process_tree(pid):
            fd_dir = self.proc_root / str(process_pid) / "fd"
            try:
                descriptors = list(fd_dir.iterdir())
            except (FileNotFoundError, PermissionError, OSError):
                continue
            for descriptor in descriptors:
                try:
                    target = os.readlink(descriptor)
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    return True
        return False


class BackendLauncher:
    """Start, recognize, and stop exactly one local GERAM CORE OS backend."""

    def __init__(
        self,
        root: Path,
        *,
        port: int,
        state_dir: Path | None = None,
        lifespan_off: bool = False,
        inspector: ProcInspector | None = None,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.root = validate_project_root(root)
        self.host = LOCAL_HOST
        if not 1 <= port <= 65535:
            raise LauncherError("APP_PORT debe ser un puerto local válido.")
        self.port = port
        self.lifespan_off = lifespan_off
        self.state_dir = (state_dir or self.root).expanduser().resolve()
        if state_dir is not None:
            self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.state_dir, 0o700)
        self.pid_file = self.state_dir / PID_FILE_NAME
        self.lock_file = self.state_dir / LOCK_FILE_NAME
        self.log_file = (
            self.root / "logs" / BACKEND_LOG_NAME
            if state_dir is None
            else self.state_dir / BACKEND_LOG_NAME
        )
        self.python = self.root / "venv/bin/python"
        self.inspector = inspector or ProcInspector()
        self._popen = popen
        self._monotonic = monotonic
        self._sleep = sleeper

    def command(
        self,
        *,
        port: int | None = None,
        lifespan_off: bool | None = None,
    ) -> list[str]:
        selected_port = self.port if port is None else port
        disable_lifespan = self.lifespan_off if lifespan_off is None else lifespan_off
        command = [
            str(self.python),
            "-m",
            "uvicorn",
            CANONICAL_ENTRYPOINT,
            "--host",
            self.host,
            "--port",
            str(selected_port),
            "--workers",
            "1",
            "--no-proxy-headers",
        ]
        if disable_lifespan:
            command.extend(("--lifespan", "off"))
        return command

    @contextmanager
    def _lock(self):
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_file, flags, 0o600)
        except OSError:
            raise LauncherError(
                "No se pudo asegurar el bloqueo local del launcher."
            ) from None
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _read_pid_record(self) -> tuple[PidRecord | None, bool]:
        try:
            file_status = self.pid_file.lstat()
        except FileNotFoundError:
            return None, False
        except OSError:
            raise LauncherError("No se pudo validar el PID file local.") from None
        if not stat.S_ISREG(file_status.st_mode):
            raise LauncherError("El PID file local no es un archivo regular seguro.")
        os.chmod(self.pid_file, 0o600)
        if file_status.st_size > MAX_PID_FILE_BYTES:
            return None, True
        try:
            payload = json.loads(self.pid_file.read_text(encoding="utf-8"))
            record = PidRecord(
                pid=int(payload["pid"]),
                start_ticks=int(payload["start_ticks"]),
                root=str(payload["root"]),
                entrypoint=str(payload["entrypoint"]),
                host=str(payload["host"]),
                port=int(payload["port"]),
                kind=str(payload["kind"]),
                lifespan_off=bool(payload.get("lifespan_off", False)),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None, True
        if record.pid <= 1 or not 1 <= record.port <= 65535:
            return None, True
        return record, False

    def _write_pid_record(self, record: PidRecord) -> None:
        descriptor = -1
        temporary_path: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f"{self.pid_file.name}.",
                suffix=".tmp",
                dir=self.state_dir,
            )
            temporary_path = Path(raw_path)
            os.fchmod(descriptor, 0o600)
            encoded = (json.dumps(asdict(record), sort_keys=True) + "\n").encode(
                "utf-8"
            )
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise OSError("incomplete PID file write")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary_path, self.pid_file)
            temporary_path = None
            os.chmod(self.pid_file, 0o600)
        except OSError:
            raise LauncherError("No se pudo escribir el PID file local.") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _remove_pid_file(self) -> None:
        try:
            file_status = self.pid_file.lstat()
        except FileNotFoundError:
            return
        except OSError:
            raise LauncherError("No se pudo limpiar el PID file local.") from None
        if not stat.S_ISREG(file_status.st_mode):
            raise LauncherError("El PID file local no es un archivo regular seguro.")
        try:
            self.pid_file.unlink()
        except OSError:
            raise LauncherError("No se pudo limpiar el PID file local.") from None

    def _canonical_kind(
        self,
        snapshot: ProcessSnapshot,
        *,
        port: int,
        lifespan_off: bool,
    ) -> str | None:
        try:
            expected_python = self.python.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return None
        if (
            snapshot.executable != expected_python
            or snapshot.cwd != self.root
        ):
            return None
        if list(snapshot.argv[1:]) == self.command(
            port=port,
            lifespan_off=lifespan_off,
        )[1:]:
            return "managed"
        if list(snapshot.argv[1:]) == ["-m", CANONICAL_MODULE]:
            return "manual"
        return None

    def _validate_record(self, record: PidRecord) -> ProcessSnapshot | None:
        if (
            record.root != str(self.root)
            or record.entrypoint != CANONICAL_ENTRYPOINT
            or record.host != self.host
            or record.kind not in {"managed", "manual"}
        ):
            return None
        snapshot = self.inspector.snapshot(record.pid)
        if snapshot is None or snapshot.start_ticks != record.start_ticks:
            return None
        kind = self._canonical_kind(
            snapshot,
            port=record.port,
            lifespan_off=record.lifespan_off,
        )
        return snapshot if kind == record.kind else None

    def _record_for(self, snapshot: ProcessSnapshot, kind: str) -> PidRecord:
        return PidRecord(
            pid=snapshot.pid,
            start_ticks=snapshot.start_ticks,
            root=str(self.root),
            entrypoint=CANONICAL_ENTRYPOINT,
            host=self.host,
            port=self.port,
            kind=kind,
            lifespan_off=self.lifespan_off if kind == "managed" else False,
        )

    def _find_canonical_processes(self) -> list[tuple[ProcessSnapshot, str]]:
        matches: list[tuple[ProcessSnapshot, str]] = []
        for snapshot in self.inspector.iter_snapshots():
            kind = self._canonical_kind(
                snapshot,
                port=self.port,
                lifespan_off=self.lifespan_off,
            )
            if kind is None:
                continue
            if kind == "manual" and not self.inspector.owns_listener(
                snapshot.pid,
                self.host,
                self.port,
            ):
                continue
            matches.append((snapshot, kind))
        return matches

    def _manual_process_exists_on_another_port(self) -> bool:
        for snapshot in self.inspector.iter_snapshots():
            if self._canonical_kind(
                snapshot,
                port=self.port,
                lifespan_off=self.lifespan_off,
            ) == "manual" and not self.inspector.owns_listener(
                snapshot.pid,
                self.host,
                self.port,
            ):
                return True
        return False

    def _port_in_use(self) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.25)
            result = probe.connect_ex((self.host, self.port))
            if result == 0:
                return True
            if result in {errno.ECONNREFUSED, errno.ETIMEDOUT}:
                return False
            raise LauncherError("No se pudo validar el puerto local.")
        except OSError:
            raise LauncherError("No se pudo validar el puerto local.") from None
        finally:
            probe.close()

    def _health_ok(self) -> bool:
        url = f"http://{self.host}:{self.port}/health"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(url, timeout=0.5) as response:
                body = response.read(1025)
                if response.status != 200 or len(body) > 1024:
                    return False
                payload = json.loads(body.decode("utf-8"))
                return isinstance(payload, dict) and payload.get("status") == "ok"
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ):
            return False

    def _wait_ready(self, record: PidRecord, timeout: float) -> bool:
        deadline = self._monotonic() + max(0.0, timeout)
        while True:
            if self._validate_record(record) is None:
                return False
            if self.inspector.owns_listener(record.pid, self.host, record.port):
                if self._health_ok():
                    return True
            if self._monotonic() >= deadline:
                return False
            self._sleep(0.1)

    def _spawn_backend(self) -> subprocess.Popen:
        if not self.python.is_file() or not os.access(self.python, os.X_OK):
            raise LauncherError(
                "No se encontró el intérprete local del entorno virtual."
            )
        self.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.log_file.parent, 0o700)
        log_descriptor = os.open(
            self.log_file,
            os.O_CREAT | os.O_WRONLY | os.O_APPEND,
            0o600,
        )
        os.fchmod(log_descriptor, 0o600)
        log_stream = os.fdopen(log_descriptor, "ab", buffering=0)
        try:
            return self._popen(
                self.command(),
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError:
            raise LauncherError("No se pudo iniciar GERAM CORE OS.") from None
        finally:
            log_stream.close()

    def _snapshot_after_spawn(self, pid: int, timeout: float = 2.0) -> ProcessSnapshot | None:
        deadline = self._monotonic() + timeout
        while self._monotonic() < deadline:
            snapshot = self.inspector.snapshot(pid)
            if snapshot is not None:
                return snapshot
            self._sleep(0.05)
        return None

    def _signal_owned(self, record: PidRecord, selected_signal: int) -> None:
        if self._validate_record(record) is None:
            raise LauncherError(
                "El proceso encontrado no pertenece a GERAM CORE OS; no se detuvo."
            )
        try:
            os.kill(record.pid, selected_signal)
        except ProcessLookupError:
            return
        except OSError:
            raise LauncherError("No se pudo detener GERAM CORE OS.") from None

    def _wait_stopped(self, record: PidRecord, timeout: float) -> bool:
        deadline = self._monotonic() + max(0.0, timeout)
        while True:
            if self._validate_record(record) is None:
                return True
            if self._monotonic() >= deadline:
                return False
            self._sleep(0.1)

    def start(self, *, timeout: float = 15.0) -> LaunchOutcome:
        warnings: list[str] = []
        with self._lock():
            record, malformed = self._read_pid_record()
            if record is not None:
                if self._validate_record(record) is not None:
                    if record.port != self.port:
                        raise LauncherError(
                            "GERAM CORE OS ya está iniciado en otro puerto local."
                        )
                    if not self._wait_ready(record, timeout):
                        raise LauncherError(
                            "El proceso legítimo de GERAM CORE OS no quedó listo."
                        )
                    return LaunchOutcome("already_running", record.pid)
                self._remove_pid_file()
                warnings.append(
                    "PID file obsoleto eliminado tras validar que no representa "
                    "un proceso legítimo de GERAM CORE OS."
                )
            elif malformed:
                self._remove_pid_file()
                warnings.append("PID file obsoleto o inválido eliminado de forma segura.")

            candidates = self._find_canonical_processes()
            if len(candidates) > 1:
                raise LauncherError(
                    "Se encontraron múltiples procesos canónicos de GERAM CORE OS; "
                    "no se inició otro."
                )
            if candidates:
                snapshot, kind = candidates[0]
                adopted = self._record_for(snapshot, kind)
                self._write_pid_record(adopted)
                if not self._wait_ready(adopted, timeout):
                    raise LauncherError(
                        "El proceso legítimo de GERAM CORE OS no quedó listo."
                    )
                return LaunchOutcome("already_running", snapshot.pid, tuple(warnings))

            if (
                not self.lifespan_off
                and self._manual_process_exists_on_another_port()
            ):
                raise LauncherError(
                    "GERAM CORE OS ya está iniciado en otro puerto local."
                )

            if self._port_in_use():
                raise LauncherError(
                    "El puerto local configurado está ocupado por un proceso que "
                    "no pertenece a GERAM CORE OS."
                )

            process = self._spawn_backend()
            snapshot = self._snapshot_after_spawn(process.pid)
            if snapshot is None:
                raise LauncherError("GERAM CORE OS falló durante el arranque.")
            kind = self._canonical_kind(
                snapshot,
                port=self.port,
                lifespan_off=self.lifespan_off,
            )
            if kind != "managed":
                raise LauncherError("GERAM CORE OS falló la validación de identidad.")
            started = self._record_for(snapshot, kind)
            self._write_pid_record(started)
            if not self._wait_ready(started, timeout):
                if self._validate_record(started) is not None:
                    self._signal_owned(started, signal.SIGTERM)
                    self._wait_stopped(started, 3.0)
                self._remove_pid_file()
                raise LauncherError("GERAM CORE OS falló durante el arranque.")
            return LaunchOutcome("started", process.pid, tuple(warnings))

    def stop(self, *, timeout: float = 10.0) -> LaunchOutcome:
        with self._lock():
            record, malformed = self._read_pid_record()
            if malformed:
                self._remove_pid_file()
                raise LauncherError(
                    "PID file obsoleto eliminado; no se detuvo ningún proceso."
                )
            if record is None:
                candidates = self._find_canonical_processes()
                if not candidates:
                    return LaunchOutcome("not_running")
                if len(candidates) > 1:
                    raise LauncherError(
                        "Se encontraron múltiples procesos canónicos; no se detuvo ninguno."
                    )
                snapshot, kind = candidates[0]
                record = self._record_for(snapshot, kind)
                self._write_pid_record(record)

            if self._validate_record(record) is None:
                self._remove_pid_file()
                raise LauncherError(
                    "PID file obsoleto eliminado: el proceso encontrado no pertenece "
                    "a GERAM CORE OS y no se detuvo."
                )

            self._signal_owned(record, signal.SIGTERM)
            if not self._wait_stopped(record, timeout):
                self._signal_owned(record, signal.SIGKILL)
                if not self._wait_stopped(record, 2.0):
                    raise LauncherError("GERAM CORE OS no se detuvo dentro del plazo.")
            self._remove_pid_file()
            return LaunchOutcome("stopped", record.pid)

    def status(self) -> LaunchOutcome:
        with self._lock():
            record, malformed = self._read_pid_record()
            if malformed:
                self._remove_pid_file()
                return LaunchOutcome("stale")
            if record is None:
                return LaunchOutcome("not_running")
            if self._validate_record(record) is None:
                self._remove_pid_file()
                return LaunchOutcome("stale")
            action = (
                "running"
                if self.inspector.owns_listener(record.pid, self.host, record.port)
                else "starting"
            )
            return LaunchOutcome(action, record.pid)


def _print_outcome(outcome: LaunchOutcome) -> None:
    for warning in outcome.warnings:
        print(f"AVISO: {warning}", file=sys.stderr)
    messages = {
        "started": "GERAM CORE OS iniciado de forma segura.",
        "already_running": "GERAM CORE OS ya estaba iniciado; no se duplicó.",
        "stopped": "GERAM CORE OS detenido y PID file limpiado.",
        "not_running": "GERAM CORE OS no está iniciado.",
        "running": "GERAM CORE OS está iniciado y validado.",
        "starting": "GERAM CORE OS está iniciando con identidad válida.",
        "stale": "El PID file de GERAM CORE OS está obsoleto.",
    }
    print(messages[outcome.action])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GERAM CORE OS local launcher")
    parser.add_argument("action", choices=("start", "stop", "restart", "status"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--wait", type=float, default=15.0)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument(
        "--no-lifespan",
        action="store_true",
        help="Disable application lifespan only for controlled local smoke tests.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        root = resolve_project_root()
        port = arguments.port if arguments.port is not None else configured_port(root)
        launcher = BackendLauncher(
            root,
            port=port,
            state_dir=arguments.state_dir,
            lifespan_off=arguments.no_lifespan,
        )
        if arguments.action == "start":
            outcome = launcher.start(timeout=arguments.wait)
        elif arguments.action == "stop":
            outcome = launcher.stop(timeout=arguments.wait)
        elif arguments.action == "restart":
            launcher.stop(timeout=arguments.wait)
            if arguments.delay > 0:
                time.sleep(arguments.delay)
            outcome = launcher.start(timeout=arguments.wait)
        else:
            outcome = launcher.status()
        _print_outcome(outcome)
        return 0 if outcome.action not in {"stale"} else 3
    except LauncherError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
