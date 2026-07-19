"""Portable-state backup, validated recovery, and secret-free diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from app.core.agent_roster import agent_roster_store
from app.core.config import settings
from app.core.gcs.integrations import integration_hub
from app.core.sandbox_backend import SandboxUnavailableError, detect_sandbox_backend


MAX_BACKUP_BYTES = 32 * 1024 * 1024
MAX_BACKUP_FILE_BYTES = 4 * 1024 * 1024
BACKUP_ID = re.compile(r"^geram-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.zip$")
ALLOWED_ROOTS = frozenset({"config", "runtime", "agents", "gcs", "extensions"})


class MaintenanceError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _backup_directory() -> Path:
    path = settings.LOCAL_DATA_DIR / "backups"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _allowed_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] not in ALLOWED_ROOTS
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise MaintenanceError("invalid_backup_path", "The backup contains an invalid path")
    return path


def _portable_files() -> list[tuple[Path, str]]:
    base = settings.LOCAL_DATA_DIR.resolve()
    files: list[tuple[Path, str]] = []
    total = 0
    for root_name in sorted(ALLOWED_ROOTS):
        root = base / root_name
        if not root.is_dir() or root.is_symlink():
            continue
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(base)
                size = resolved.stat().st_size
            except (OSError, ValueError):
                continue
            if size > MAX_BACKUP_FILE_BYTES:
                continue
            total += size
            if total > MAX_BACKUP_BYTES:
                raise MaintenanceError("backup_too_large", "Portable state exceeds the backup limit")
            files.append((resolved, resolved.relative_to(base).as_posix()))
    return files


def create_backup(label: str = "manual") -> dict[str, object]:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_id = f"geram-{timestamp}-{uuid.uuid4().hex[:8]}.zip"
    target = _backup_directory() / backup_id
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".backup-", suffix=".tmp")
    os.close(descriptor)
    entries = []
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, relative in _portable_files():
                data = path.read_bytes()
                archive.writestr(relative, data)
                entries.append({
                    "path": relative,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                })
            manifest = {
                "format": 1,
                "created_at": timestamp,
                "label": str(label)[:40],
                "files": entries,
            }
            archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        os.replace(temporary, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {"id": backup_id, "created_at": timestamp, "label": str(label)[:40], "files": len(entries)}


def _manifest(archive: zipfile.ZipFile) -> dict:
    try:
        info = archive.getinfo("manifest.json")
        if info.file_size > 256 * 1024:
            raise MaintenanceError("invalid_backup", "Backup manifest is too large")
        manifest = json.loads(archive.read(info).decode("utf-8"))
    except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise MaintenanceError("invalid_backup", "Backup manifest is invalid") from None
    if not isinstance(manifest, dict) or manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
        raise MaintenanceError("invalid_backup", "Backup format is unsupported")
    return manifest


def list_backups() -> list[dict[str, object]]:
    result = []
    for path in sorted(_backup_directory().glob("geram-*.zip"), reverse=True):
        if not BACKUP_ID.fullmatch(path.name) or path.is_symlink():
            continue
        try:
            with zipfile.ZipFile(path, "r") as archive:
                manifest = _manifest(archive)
            result.append({
                "id": path.name,
                "created_at": str(manifest.get("created_at", ""))[:32],
                "label": str(manifest.get("label", ""))[:40],
                "files": len(manifest["files"]),
                "size": path.stat().st_size,
            })
        except (OSError, zipfile.BadZipFile, MaintenanceError):
            continue
    return result[:50]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".restore-", suffix=".tmp")
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def restore_backup(backup_id: str) -> dict[str, object]:
    if not BACKUP_ID.fullmatch(backup_id):
        raise MaintenanceError("invalid_backup_id", "Backup id is invalid")
    target = (_backup_directory() / backup_id).resolve()
    try:
        target.relative_to(_backup_directory().resolve())
    except ValueError:
        raise MaintenanceError("invalid_backup_id", "Backup id is invalid") from None
    if not target.is_file() or target.is_symlink():
        raise MaintenanceError("backup_not_found", "Backup does not exist")

    try:
        with zipfile.ZipFile(target, "r") as archive:
            manifest = _manifest(archive)
            by_name = {info.filename: info for info in archive.infolist()}
            payloads: list[tuple[PurePosixPath, bytes]] = []
            total = 0
            seen: set[str] = set()
            for entry in manifest["files"]:
                if not isinstance(entry, dict):
                    raise MaintenanceError("invalid_backup", "Backup file metadata is invalid")
                relative = _allowed_relative(str(entry.get("path", "")))
                name = relative.as_posix()
                if name in seen or name not in by_name:
                    raise MaintenanceError("invalid_backup", "Backup file list is inconsistent")
                seen.add(name)
                info = by_name[name]
                if info.is_dir() or info.file_size > MAX_BACKUP_FILE_BYTES:
                    raise MaintenanceError("invalid_backup", "Backup contains an oversized file")
                data = archive.read(info)
                total += len(data)
                if total > MAX_BACKUP_BYTES or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                    raise MaintenanceError("invalid_backup", "Backup integrity validation failed")
                payloads.append((relative, data))
    except zipfile.BadZipFile:
        raise MaintenanceError("invalid_backup", "Backup archive is invalid") from None

    safety = create_backup("pre-restore")
    base = settings.LOCAL_DATA_DIR.resolve()
    for relative, data in payloads:
        destination = base.joinpath(*relative.parts)
        _atomic_write(destination, data)
    return {"status": "restored", "id": backup_id, "files": len(payloads), "safety_backup": safety["id"]}


def diagnostics() -> dict[str, object]:
    try:
        sandbox = detect_sandbox_backend().name == "bubblewrap"
    except SandboxUnavailableError:
        sandbox = False
    roster = agent_roster_store.list_all()
    return {
        "version": "0.1.0",
        "platform": {
            "system": platform.system() or "Unknown",
            "wsl2": bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in platform.release().lower(),
        },
        "checks": {
            "local_data_available": settings.LOCAL_DATA_DIR.parent.exists(),
            "workspace_available": settings.WORKSPACE_ROOT.is_dir(),
            "sandbox_available": sandbox,
            "loopback_only": settings.APP_HOST in {"127.0.0.1", "localhost", "::1"},
        },
        "agents": {
            "total": len(roster),
            "enabled": sum(bool(agent["enabled"]) for agent in roster),
            "loaded": sum(bool(agent["loaded"]) for agent in roster),
        },
        "integrations": [
            {"id": item["id"], "state": item["state"]}
            for item in integration_hub.list_integrations()
        ],
        "backups": len(list_backups()),
        "secrets_included": False,
    }
