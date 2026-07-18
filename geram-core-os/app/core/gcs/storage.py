"""
Shared local-storage helpers for the GERAM Core System (GCS).

Every GCS service that persists user content (custom skills, user-created
agents, integration connection state) writes JSON documents under a bounded
subdirectory of ``settings.LOCAL_DATA_DIR`` — which is guaranteed by
``app/core/config.py`` to live OUTSIDE the application source tree.

Two properties are non-negotiable and centralized here so no individual
service can get them wrong:

  * **Atomic ``0600`` writes** — owner-only, never a half-written file.
  * **Traversal-proof identifiers** — a document id can never escape its
    directory (no ``..``, no separators, no absolute paths). Custom content
    is treated as UNTRUSTED, so ids are validated before they ever touch the
    filesystem.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from app.core.config import settings

# A stable id is a short, lowercase, filesystem-safe slug. This is the single
# gate that makes ``<data_dir>/<id>.json`` traversal-proof: no dots, slashes,
# or path separators can survive it, so ".." / "a/b" / "/etc/x" are rejected.
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Hard ceiling for any single persisted document. Custom content is untrusted;
# this bounds memory use when loading and blocks accidental/hostile bloat.
MAX_DOCUMENT_BYTES = 256 * 1024


class StorageError(ValueError):
    """A storage-layer problem that is safe to surface without leaking input."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def validate_id(value: str, *, kind: str = "id") -> str:
    """Return a validated, traversal-proof stable id or raise ``StorageError``."""
    normalized = str(value).strip().lower()
    if not _ID_PATTERN.fullmatch(normalized):
        raise StorageError(
            f"invalid_{kind}",
            f"{kind} must be 1-64 chars of [a-z0-9_-] and start alphanumeric",
        )
    return normalized


def gcs_data_dir(*parts: str) -> Path:
    """Resolve (and create) a bounded subdirectory under ``LOCAL_DATA_DIR``.

    The result is always confined to ``LOCAL_DATA_DIR/gcs/...``; callers pass
    fixed literal segments (e.g. ``"skills", "custom"``), never user input.
    """
    base = (settings.LOCAL_DATA_DIR / "gcs").resolve()
    target = base.joinpath(*parts).resolve()
    # Defensive: the fixed call sites cannot escape, but assert it anyway so a
    # future careless caller fails closed instead of writing outside the box.
    target.relative_to(base)
    target.mkdir(parents=True, exist_ok=True)
    return target


def document_path(directory: Path, stable_id: str, *, kind: str = "id") -> Path:
    """Return the on-disk path for ``<directory>/<validated id>.json``."""
    safe_id = validate_id(stable_id, kind=kind)
    path = (directory / f"{safe_id}.json").resolve()
    path.relative_to(directory.resolve())  # belt-and-suspenders traversal check
    return path


def write_json_atomic_0600(path: Path, payload: dict) -> None:
    """Serialize ``payload`` and write it atomically with owner-only perms."""
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise StorageError("document_too_large", "document exceeds the size limit")
    directory = path.parent
    handle, temporary = tempfile.mkstemp(dir=str(directory), prefix=".gcs-", suffix=".tmp")
    try:
        if hasattr(os, "fchmod"):  # Unix-only; en Windows lo maneja el perfil de usuario
            os.fchmod(handle, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_json(path: Path) -> dict:
    """Read a JSON document, bounding its size first. Raises on bad content."""
    try:
        size = path.stat().st_size
    except OSError as error:
        raise StorageError("unreadable_document", "document could not be read") from error
    if size > MAX_DOCUMENT_BYTES:
        raise StorageError("document_too_large", "document exceeds the size limit")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StorageError("invalid_document", "document must be a JSON object")
    return raw


def list_document_ids(directory: Path) -> list[str]:
    """List valid stable ids of persisted ``*.json`` documents in ``directory``."""
    if not directory.is_dir():
        return []
    ids: list[str] = []
    for entry in sorted(directory.glob("*.json")):
        if entry.name.startswith("."):
            continue
        try:
            ids.append(validate_id(entry.stem))
        except StorageError:
            # Ignore anything that isn't a clean id — never trust the FS blindly.
            continue
    return ids


def delete_document(path: Path) -> bool:
    """Remove a persisted document; return False if it did not exist."""
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
