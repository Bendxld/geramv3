#!/usr/bin/env python3
"""Create/verify deterministic release checksums and an optional GPG signature."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


ARTIFACT_SUFFIXES = (".AppImage", ".deb", ".exe", ".blockmap", ".yml")


def artifacts(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.name != "SHA256SUMS" and not path.name.endswith((".asc", ".sig"))
        and path.name.endswith(ARTIFACT_SUFFIXES)
    )


def write_checksums(directory: Path) -> Path:
    selected = artifacts(directory)
    if not selected:
        raise RuntimeError("no release artifacts found")
    output = directory / "SHA256SUMS"
    lines = []
    for path in selected:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}\n")
    output.write_text("".join(lines), encoding="ascii")
    return output


def verify_checksums(directory: Path) -> None:
    checksum_file = directory / "SHA256SUMS"
    for raw in checksum_file.read_text(encoding="ascii").splitlines():
        digest, separator, name = raw.partition("  ")
        if separator != "  " or len(digest) != 64 or Path(name).name != name:
            raise RuntimeError("invalid checksum manifest")
        target = directory / name
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"checksum mismatch: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--sign", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve(strict=True)
    if args.verify:
        verify_checksums(directory)
        signature = directory / "SHA256SUMS.asc"
        if signature.is_file():
            subprocess.run(["gpg", "--batch", "--verify", str(signature), str(directory / "SHA256SUMS")], check=True)
        return 0
    checksum_file = write_checksums(directory)
    if args.sign:
        subprocess.run([
            "gpg", "--batch", "--yes", "--armor", "--detach-sign", str(checksum_file)
        ], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
