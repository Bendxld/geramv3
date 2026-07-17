#!/usr/bin/env python3
"""Safe local desktop lifecycle for GERAM CORE OS on Linux."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from launcher import BackendLauncher, LauncherError, configured_port, validate_project_root


ROOT = Path(__file__).resolve().parent
ELECTRON_BINARY_RELATIVE = Path("electron/node_modules/electron/dist/electron")
ELECTRON_APP_RELATIVE = Path("electron")
PID_FILE_NAME = ".electron_app.pid"
LOCK_FILE_NAME = ".electron_app.pid.lock"
LOG_RELATIVE = Path("logs/desktop_launcher.log")
MAX_STATE_BYTES = 4096
ALLOWED_ENVIRONMENT_NAMES = frozenset({
    "DBUS_SESSION_BUS_ADDRESS",
    "DESKTOP_STARTUP_ID",
    "DISPLAY",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "SHELL",
    "USER",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_CONFIG_HOME",
    "XDG_CURRENT_DESKTOP",
    "XDG_DATA_DIRS",
    "XDG_DATA_HOME",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
})


class DesktopLauncherError(RuntimeError):
    """A sanitized desktop-launch failure safe to show to the local user."""


@dataclass(frozen=True)
class ElectronRecord:
    pid: int
    start_ticks: int
    root: str
    port: int
    backend_owned: bool
    lifespan_off: bool


def _process_start_ticks(pid: int) -> int | None:
    try:
        fields = Path("/proc", str(pid), "stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
        return int(fields[19])
    except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
        return None


def _electron_environment(port: int, source: dict[str, str] | None = None) -> dict[str, str]:
    inherited = os.environ if source is None else source
    environment = {
        name: value
        for name, value in inherited.items()
        if name in ALLOWED_ENVIRONMENT_NAMES or name.startswith("LC_")
    }
    environment["PATH"] = "/usr/bin:/bin"
    environment["GERAM_ELECTRON_PORT"] = str(port)
    return environment


def _default_notifier(message: str, *, error: bool) -> None:
    urgency = "critical" if error else "normal"
    command = [
        "/usr/bin/notify-send",
        "--app-name=GERAM CORE OS",
        f"--urgency={urgency}",
        "GERAM CORE OS",
        message,
    ]
    try:
        subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
            env=_electron_environment(8000),
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        print(f"GERAM CORE OS: {message}", file=sys.stderr)


class DesktopLauncher:
    def __init__(
        self,
        root: Path,
        *,
        port: int,
        lifespan_off: bool = False,
        backend_factory: Callable[..., BackendLauncher] = BackendLauncher,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        notifier: Callable[..., None] = _default_notifier,
        geteuid: Callable[[], int] = os.geteuid,
    ):
        self.root = validate_project_root(root)
        if not 1 <= port <= 65535:
            raise DesktopLauncherError("El puerto local configurado no es válido.")
        self.port = port
        self.lifespan_off = lifespan_off
        self.backend_factory = backend_factory
        self.popen = popen
        self.notifier = notifier
        self.geteuid = geteuid
        self.electron_binary = (self.root / ELECTRON_BINARY_RELATIVE).resolve()
        self.electron_app = (self.root / ELECTRON_APP_RELATIVE).resolve()
        self.pid_file = self.root / PID_FILE_NAME
        self.lock_file = self.root / LOCK_FILE_NAME
        self.log_file = self.root / LOG_RELATIVE

    def _log(self, event: str) -> None:
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-= ")
        if not event or any(character not in allowed for character in event):
            event = "invalid_log_event"
        self.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.log_file.parent, 0o700)
        flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.log_file, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
            os.write(descriptor, f"{timestamp} {event}\n".encode("ascii", "replace"))
        except OSError:
            raise DesktopLauncherError("No se pudo escribir el log local de arranque.") from None
        finally:
            if "descriptor" in locals():
                os.close(descriptor)

    def _notify(self, message: str, *, error: bool) -> None:
        self.notifier(message, error=error)

    def _verify_runtime(self) -> None:
        if self.geteuid() == 0:
            raise DesktopLauncherError("GERAM CORE OS no debe ejecutarse como root.")
        if not self.electron_binary.is_file() or not os.access(self.electron_binary, os.X_OK):
            raise DesktopLauncherError(
                "No se encontró Electron local. Ejecuta la preparación de dependencias del proyecto."
            )
        if not (self.electron_app / "main.js").is_file():
            raise DesktopLauncherError("La aplicación Electron de GERAM CORE OS está incompleta.")

    def _acquire_lock(self) -> int | None:
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_file, flags, 0o600)
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return descriptor
        except BlockingIOError:
            if "descriptor" in locals():
                os.close(descriptor)
            return None
        except OSError:
            if "descriptor" in locals():
                os.close(descriptor)
            raise DesktopLauncherError("No se pudo asegurar el bloqueo de la aplicación.") from None

    def _release_lock(self, descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    def _read_record(self) -> tuple[ElectronRecord | None, bool]:
        try:
            status = self.pid_file.lstat()
        except FileNotFoundError:
            return None, False
        except OSError:
            raise DesktopLauncherError("No se pudo validar el estado local de Electron.") from None
        if not stat.S_ISREG(status.st_mode):
            raise DesktopLauncherError("El estado local de Electron no es un archivo seguro.")
        os.chmod(self.pid_file, 0o600)
        if status.st_size > MAX_STATE_BYTES:
            return None, True
        try:
            payload = json.loads(self.pid_file.read_text(encoding="utf-8"))
            record = ElectronRecord(
                pid=int(payload["pid"]),
                start_ticks=int(payload["start_ticks"]),
                root=str(payload["root"]),
                port=int(payload["port"]),
                backend_owned=bool(payload["backend_owned"]),
                lifespan_off=bool(payload.get("lifespan_off", False)),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None, True
        return record, False

    def _write_record(self, record: ElectronRecord) -> None:
        payload = json.dumps(record.__dict__, sort_keys=True, separators=(",", ":")) + "\n"
        descriptor = -1
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{PID_FILE_NAME}.",
                dir=self.root,
                text=True,
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload.encode("utf-8"))
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary_path, self.pid_file)
            temporary_path = None
            os.chmod(self.pid_file, 0o600)
        except OSError:
            raise DesktopLauncherError("No se pudo guardar el estado local de Electron.") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _remove_record(self) -> None:
        try:
            status = self.pid_file.lstat()
        except FileNotFoundError:
            return
        except OSError:
            raise DesktopLauncherError("No se pudo limpiar el estado local de Electron.") from None
        if not stat.S_ISREG(status.st_mode):
            raise DesktopLauncherError("El estado local de Electron no es un archivo seguro.")
        try:
            self.pid_file.unlink()
        except OSError:
            raise DesktopLauncherError("No se pudo limpiar el estado local de Electron.") from None

    def _validate_electron(self, record: ElectronRecord) -> bool:
        if record.root != str(self.root) or record.port != self.port:
            return False
        if _process_start_ticks(record.pid) != record.start_ticks:
            return False
        proc = Path("/proc", str(record.pid))
        try:
            executable = (proc / "exe").resolve(strict=True)
            cwd = (proc / "cwd").resolve(strict=True)
            argv = [item for item in (proc / "cmdline").read_bytes().split(b"\0") if item]
        except (FileNotFoundError, PermissionError, OSError):
            return False
        if executable != self.electron_binary or cwd != self.root:
            return False
        expected_command = os.fsencode(str(self.electron_binary))
        expected_application = os.fsencode(str(self.electron_app))
        # Electron updates process.title after ready. On Linux that can flatten
        # the original two argv entries into one exact cmdline string.
        return argv in (
            [expected_command, expected_application],
            [expected_command + b" " + expected_application],
        )

    def _wait_for_identity(self, pid: int, timeout: float = 3.0) -> ElectronRecord | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            start_ticks = _process_start_ticks(pid)
            if start_ticks is not None:
                record = ElectronRecord(
                    pid=pid,
                    start_ticks=start_ticks,
                    root=str(self.root),
                    port=self.port,
                    backend_owned=False,
                    lifespan_off=self.lifespan_off,
                )
                if self._validate_electron(record):
                    return record
            time.sleep(0.05)
        return None

    def _terminate_electron(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, OSError):
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
                raise DesktopLauncherError("Electron no se pudo cerrar de forma limpia.") from None

    def run(self) -> int:
        self._verify_runtime()
        descriptor = self._acquire_lock()
        if descriptor is None:
            self._log("desktop_already_open")
            self._notify("GERAM CORE OS ya está abierto; no se inició otra ventana.", error=False)
            return 0

        backend: BackendLauncher | None = None
        backend_owned = False
        electron: subprocess.Popen | None = None
        record_owned = False
        try:
            existing, malformed = self._read_record()
            if existing is not None and self._validate_electron(existing):
                self._log("electron_already_running")
                self._notify("GERAM CORE OS ya está abierto; no se inició otra ventana.", error=False)
                return 0
            if existing is not None or malformed:
                self._remove_record()
                self._log("stale_electron_state_removed")

            backend = self.backend_factory(
                self.root,
                port=self.port,
                lifespan_off=self.lifespan_off,
            )
            outcome = backend.start(timeout=20.0)
            backend_owned = outcome.action == "started"
            self._log(f"backend_{outcome.action} port={self.port}")

            environment = _electron_environment(self.port)
            try:
                electron = self.popen(
                    [str(self.electron_binary), str(self.electron_app)],
                    cwd=self.root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError:
                raise DesktopLauncherError("No se pudo iniciar la ventana de GERAM CORE OS.") from None

            identity = self._wait_for_identity(electron.pid)
            if identity is None:
                raise DesktopLauncherError("Electron falló la validación de identidad local.")
            record = ElectronRecord(
                pid=identity.pid,
                start_ticks=identity.start_ticks,
                root=identity.root,
                port=identity.port,
                backend_owned=backend_owned,
                lifespan_off=self.lifespan_off,
            )
            self._write_record(record)
            record_owned = True
            self._log(f"electron_started pid={electron.pid}")
            return_code = electron.wait()
            self._log(f"electron_exited code={return_code}")
            if return_code not in {0, -signal.SIGTERM}:
                raise DesktopLauncherError("La ventana de GERAM CORE OS terminó con un error.")
            return 0
        finally:
            cleanup_error: DesktopLauncherError | None = None
            try:
                if electron is not None:
                    self._terminate_electron(electron)
            except DesktopLauncherError as error:
                cleanup_error = error
            try:
                if backend is not None and backend_owned:
                    try:
                        outcome = backend.stop(timeout=10.0)
                        self._log(f"backend_{outcome.action} port={self.port}")
                    except LauncherError:
                        self._log("backend_cleanup_failed")
                        self._notify(
                            "La ventana cerró, pero el backend local requiere revisión. Consulta el log de arranque.",
                            error=True,
                        )
                        cleanup_error = DesktopLauncherError("No se pudo limpiar el backend local.")
                if record_owned:
                    self._remove_record()
            finally:
                self._release_lock(descriptor)
            if cleanup_error is not None:
                raise cleanup_error

    def stop(self) -> int:
        self._verify_runtime()
        record, malformed = self._read_record()
        if malformed:
            self._remove_record()
            self._log("invalid_electron_state_removed")
            self._notify("No había una ventana válida de GERAM CORE OS para cerrar.", error=False)
            return 0
        if record is None or not self._validate_electron(record):
            if record is not None:
                self._remove_record()
            self._log("electron_not_running")
            self._notify("GERAM CORE OS no está abierto.", error=False)
            return 0
        try:
            os.kill(record.pid, signal.SIGTERM)
        except ProcessLookupError:
            self._remove_record()
            return 0
        except OSError:
            raise DesktopLauncherError("No se pudo cerrar la ventana de GERAM CORE OS.") from None
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if not self._validate_electron(record):
                self._notify("GERAM CORE OS se cerró correctamente.", error=False)
                return 0
            time.sleep(0.1)
        raise DesktopLauncherError("La ventana de GERAM CORE OS no se cerró dentro del plazo.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GERAM CORE OS Linux desktop launcher")
    parser.add_argument("--stop", action="store_true", help="Close the validated local desktop window")
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--no-lifespan", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        port = arguments.port if arguments.port is not None else configured_port(ROOT)
        desktop = DesktopLauncher(ROOT, port=port, lifespan_off=arguments.no_lifespan)
        return desktop.stop() if arguments.stop else desktop.run()
    except (DesktopLauncherError, LauncherError) as error:
        try:
            if "desktop" in locals() and os.geteuid() != 0:
                desktop._log("desktop_startup_failed")
        except DesktopLauncherError:
            pass
        _default_notifier(str(error), error=True)
        return 1
    except Exception:
        try:
            if "desktop" in locals() and os.geteuid() != 0:
                desktop._log("desktop_internal_error")
        except DesktopLauncherError:
            pass
        _default_notifier(
            "Ocurrió un fallo interno al abrir GERAM CORE OS. Consulta el log local de arranque.",
            error=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
