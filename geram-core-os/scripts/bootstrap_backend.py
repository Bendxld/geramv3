#!/usr/bin/env python3
"""Install/update the bundled backend offline, then launch or stop it safely."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path


PID_FILE = "managed-backend.json"


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.4) as response:
            payload = json.loads(response.read(1024).decode("utf-8"))
        return response.status == 200 and payload.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".managed-", suffix=".tmp")
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def _start_ticks(pid: int) -> int:
    raw = Path("/proc", str(pid), "stat").read_text(encoding="ascii")
    return int(raw.rsplit(")", 1)[1].split()[19])


def _install(payload: Path, data_dir: Path) -> tuple[Path, Path]:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("GERAM release backend requires Python 3.12")
    payload = payload.expanduser().resolve(strict=True)
    data_dir = data_dir.expanduser().resolve()
    release = json.loads((payload / "release.json").read_text(encoding="utf-8"))
    source = (payload / "source").resolve(strict=True)
    wheels = (payload / "wheels").resolve(strict=True)
    backend = data_dir / "backend"
    marker = data_dir / "installed-release.json"
    installed = {}
    try: installed = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError): pass

    if installed.get("version") != release.get("version") or not (backend / "app" / "main.py").is_file():
        data_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=data_dir, prefix="backend-next-"))
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True)
            if (backend / ".env").is_file():
                shutil.copy2(backend / ".env", staging / ".env")
            elif (staging / ".env.example").is_file():
                shutil.copy2(staging / ".env.example", staging / ".env")
            previous = data_dir / "backend-previous"
            if previous.exists(): shutil.rmtree(previous)
            if backend.exists(): os.replace(backend, previous)
            os.replace(staging, backend)
            if previous.exists(): shutil.rmtree(previous)
        except BaseException:
            if staging.exists(): shutil.rmtree(staging)
            raise

    environment = data_dir / "venv"
    environment_marker = environment / ".geram-requirements"
    expected = str(release.get("requirements_sha256", ""))
    if not environment_marker.is_file() or environment_marker.read_text(encoding="ascii", errors="ignore") != expected:
        if environment.exists(): shutil.rmtree(environment)
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        wheel_files = list(wheels.iterdir())
        if not wheel_files:
            raise RuntimeError("release payload has no offline dependency wheels")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-index", "--find-links", str(wheels), "-r", str(backend / "requirements-lock.txt")],
            check=True,
            stdin=subprocess.DEVNULL,
        )
        environment_marker.write_text(expected, encoding="ascii")
    _atomic_json(marker, release)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return backend, python


def _stop(data_dir: Path, owner_token: str) -> int:
    pid_path = data_dir.expanduser() / PID_FILE
    try:
        record = json.loads(pid_path.read_text(encoding="utf-8"))
        pid = int(record["pid"])
        if record.get("owner_token") != owner_token or _start_ticks(pid) != int(record["start_ticks"]):
            return 0
        cwd = Path("/proc", str(pid), "cwd").resolve(strict=True)
        backend = (data_dir.expanduser() / "backend").resolve(strict=True)
        command = Path("/proc", str(pid), "cmdline").read_bytes().split(b"\0")
        if cwd != backend or b"uvicorn" not in command or b"app.main:app" not in command:
            return 0
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        deadline = time.monotonic() + 5
        while Path("/proc", str(pid)).exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--owner-token", required=True)
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or len(args.owner_token) != 32 or any(c not in "0123456789abcdef" for c in args.owner_token):
        raise SystemExit("invalid managed-backend arguments")
    if args.stop:
        return _stop(args.data_dir, args.owner_token)
    if args.payload is None:
        raise SystemExit("payload is required")
    if _health(args.port):
        return 0
    backend, python = _install(args.payload, args.data_dir)
    if not args.launch:
        return 0
    os.chdir(backend)
    try: os.setsid()
    except (AttributeError, OSError): pass
    pid = os.getpid()
    _atomic_json(args.data_dir.expanduser() / PID_FILE, {
        "pid": pid,
        "start_ticks": _start_ticks(pid),
        "owner_token": args.owner_token,
        "port": args.port,
    })
    os.environ["GERAM_LOCAL_DATA_DIR"] = str(args.data_dir.expanduser().resolve())
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = [str(python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)]
    os.execv(str(python), argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
