#!/usr/bin/env python3
"""Build the OS-neutral backend source payload consumed by Electron releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
DEFAULT_OUTPUT = ROOT / "build" / "backend-payload"
VERSION = "0.1.0"


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in {"__pycache__", ".pytest_cache", ".git", "node_modules", "venv", "dist", "build"}
        or name.endswith((".pyc", ".pyo"))
    }


def _copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, ignore=_ignore)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def prepare(output: Path, *, download_wheels: bool) -> Path:
    output = output.resolve()
    filesystem_root = Path(output.anchor)
    if output in {filesystem_root, ROOT.parent, ROOT}:
        raise ValueError("invalid release payload path")
    if output.exists():
        shutil.rmtree(output)
    source = output / "source"
    source.mkdir(parents=True)

    for name in ("app", "static"):
        _copy(ROOT / name, source / name)
    agents = REPOSITORY / "agents"
    if not agents.is_dir():
        raise RuntimeError("the bundled agents directory is missing")
    _copy(agents, source / "agents")
    for name in ("requirements.txt", "requirements-lock.txt", ".env.example", "README.md"):
        _copy(ROOT / name, source / name)
    _copy(ROOT / "electron" / "node_modules" / "pyright", source / "electron" / "node_modules" / "pyright")
    _copy(ROOT / "electron" / "licenses", source / "electron" / "licenses")
    _copy(Path(__file__).with_name("bootstrap_backend.py"), output / "bootstrap_backend.py")

    requirements = (ROOT / "requirements-lock.txt").read_bytes()
    release = {
        "format": 1,
        "version": VERSION,
        "requirements_sha256": hashlib.sha256(requirements).hexdigest(),
    }
    (output / "release.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    wheels = output / "wheels"
    wheels.mkdir()
    if download_wheels:
        subprocess.run(
            [sys.executable, "-m", "pip", "download", "--dest", str(wheels), "-r", str(ROOT / "requirements-lock.txt")],
            check=True,
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--download-wheels", action="store_true")
    args = parser.parse_args()
    prepared = prepare(args.output, download_wheels=args.download_wheels)
    print(prepared)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
