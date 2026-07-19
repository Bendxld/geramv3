"""Descriptor-safe, collision-free workspace file operations."""
from __future__ import annotations

import ctypes
import errno
import os
import re
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Any, Iterator

from app.core.workspace import MAX_TREE_ENTRIES, WorkspaceError, WorkspaceService, _public_error

MAX_NAME_LENGTH = 120
MAX_OPERATION_ENTRIES = MAX_TREE_ENTRIES
PREVIEW_TTL_SECONDS = 300
_NAME = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,120}$")
_RENAME_NOREPLACE = 1


def _safe_name(value: object) -> str:
    if not isinstance(value, str) or value in {".", ".."} or value != value.strip() or not _NAME.fullmatch(value):
        raise _public_error("invalid_name", "The item name is invalid", 422)
    return value


def _join(parent: str, name: str) -> str:
    return PurePosixPath(parent, name).as_posix() if parent else name


def _rename_noreplace(source_fd: int, source: str, destination_fd: int, destination: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise _public_error("atomic_rename_unavailable", "Atomic file operations are unavailable", 503)
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(source_fd, os.fsencode(source), destination_fd, os.fsencode(destination), _RENAME_NOREPLACE) == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise _public_error("name_collision", "An item already exists at the destination", 409)
    if code in {errno.ENOENT, errno.ENOTDIR}:
        raise _public_error("not_found", "The requested item does not exist", 404)
    raise _public_error("operation_failed", "The file operation could not be completed", 409)


class WorkspaceOperations:
    def __init__(self, workspace: WorkspaceService):
        self.workspace = workspace
        self._lock = threading.RLock()
        self._previews: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _directory_flags() -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        return flags

    @contextmanager
    def _directory(self, relative: str) -> Iterator[int]:
        descriptors: list[int] = []
        try:
            current = os.open(self.workspace.root, self._directory_flags())
            descriptors.append(current)
            if relative:
                resolved = self.workspace.resolve_path(relative)
                if len(resolved.parts) > self.workspace.max_tree_depth:
                    raise _public_error("depth_limit", "The workspace depth limit was exceeded", 422)
                for part in resolved.parts:
                    current = os.open(part, self._directory_flags(), dir_fd=current)
                    descriptors.append(current)
            yield current
        except WorkspaceError:
            raise
        except FileNotFoundError:
            raise _public_error("not_found", "The requested directory does not exist", 404) from None
        except OSError:
            raise _public_error("invalid_directory", "The requested directory is unavailable", 403) from None
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _parent_and_name(self, path: str) -> tuple[str, str]:
        resolved = self.workspace.resolve_path(path)
        return PurePosixPath(*resolved.parts[:-1]).as_posix() if len(resolved.parts) > 1 else "", resolved.parts[-1]

    def _validate_destination(self, parent: str, name: object) -> tuple[str, str]:
        safe_name = _safe_name(name)
        target = _join(parent, safe_name)
        resolved = self.workspace.resolve_path(target)
        if len(resolved.parts) > self.workspace.max_tree_depth + 1:
            raise _public_error("depth_limit", "The workspace depth limit was exceeded", 422)
        return target, safe_name

    def _require_missing(self, path: str) -> None:
        parent, name = self._parent_and_name(path)
        with self._directory(parent) as parent_fd:
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            except OSError:
                raise _public_error("operation_failed", "The destination could not be validated", 409) from None
        raise _public_error("name_collision", "An item already exists at the destination", 409)

    def _identity_and_type(self, path: str) -> tuple[tuple[int, int], str]:
        parent, name = self._parent_and_name(path)
        with self._directory(parent) as parent_fd:
            try:
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise _public_error("not_found", "The requested item does not exist", 404) from None
            if stat.S_ISLNK(info.st_mode):
                raise _public_error("symlink_not_allowed", "Symbolic links are not editable", 403)
            if stat.S_ISREG(info.st_mode):
                self.workspace._reject_hardlink(info)
                self.workspace.read_file(path)
                kind = "file"
            elif stat.S_ISDIR(info.st_mode):
                kind = "directory"
            else:
                raise _public_error("invalid_item", "The requested item is unavailable", 403)
            return (info.st_dev, info.st_ino), kind

    def _scan(self, path: str) -> tuple[int, list[str], tuple[tuple[Any, ...], ...]]:
        identity, kind = self._identity_and_type(path)
        affected: list[str] = []
        root_info = os.lstat(self.workspace.root / path)
        fingerprints: list[tuple[Any, ...]] = [
            (path, identity[0], identity[1], root_info.st_mode, root_info.st_size, root_info.st_mtime_ns)
        ]
        if kind == "file":
            return 1, [path], tuple(fingerprints)

        def walk(directory_fd: int, relative: str, depth: int) -> None:
            if depth > self.workspace.max_tree_depth + 1:
                raise _public_error("depth_limit", "The workspace depth limit was exceeded", 422)
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if len(affected) >= MAX_OPERATION_ENTRIES:
                        raise _public_error("operation_too_large", "The operation contains too many items", 413)
                    child = _join(relative, entry.name)
                    self.workspace.resolve_path(child)
                    if entry.is_symlink():
                        raise _public_error("symlink_not_allowed", "Symbolic links are not editable", 403)
                    info = entry.stat(follow_symlinks=False)
                    fingerprints.append((child, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns))
                    if stat.S_ISREG(info.st_mode):
                        self.workspace._reject_hardlink(info)
                        self.workspace.read_file(child)
                        affected.append(child)
                    elif stat.S_ISDIR(info.st_mode):
                        affected.append(child)
                        child_fd = os.open(entry.name, self._directory_flags(), dir_fd=directory_fd)
                        try:
                            walk(child_fd, child, depth + 1)
                        finally:
                            os.close(child_fd)
                    else:
                        raise _public_error("invalid_item", "The requested item is unavailable", 403)

        with self._directory(path) as directory_fd:
            walk(directory_fd, path, len(PurePosixPath(path).parts))
        return len(affected) + 1, [path] + affected, tuple(fingerprints)

    def create(self, parent: str, name: object, kind: str) -> dict[str, Any]:
        if kind not in {"file", "directory"}:
            raise _public_error("invalid_item_type", "The item type is invalid", 422)
        target, safe_name = self._validate_destination(parent, name)
        with self._lock, self._directory(parent) as parent_fd:
            try:
                if kind == "directory":
                    os.mkdir(safe_name, 0o700, dir_fd=parent_fd)
                else:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if hasattr(os, "O_CLOEXEC"):
                        flags |= os.O_CLOEXEC
                    if hasattr(os, "O_NOFOLLOW"):
                        flags |= os.O_NOFOLLOW
                    descriptor = os.open(safe_name, flags, 0o600, dir_fd=parent_fd)
                    os.close(descriptor)
            except FileExistsError:
                raise _public_error("name_collision", "An item already exists at the destination", 409) from None
            except OSError:
                raise _public_error("operation_failed", "The item could not be created", 409) from None
        return {"path": target, "type": kind}

    def duplicate(self, source: str, name: object) -> dict[str, Any]:
        parent, _source_name = self._parent_and_name(source)
        target, safe_name = self._validate_destination(parent, name)
        document = self.workspace.read_file(source)
        data = document["content"].encode("utf-8")
        with self._lock, self._directory(parent) as parent_fd:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = -1
            try:
                descriptor = os.open(safe_name, flags, 0o600, dir_fd=parent_fd)
                self.workspace._write_all(descriptor, data)
                os.fsync(descriptor)
            except FileExistsError:
                raise _public_error("name_collision", "An item already exists at the destination", 409) from None
            except OSError:
                if descriptor >= 0:
                    try:
                        os.unlink(safe_name, dir_fd=parent_fd)
                    except OSError:
                        pass
                raise _public_error("operation_failed", "The item could not be duplicated", 409) from None
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        return {"path": target, "type": "file"}

    def preview_move(self, source: str, destination_parent: str, name: object | None = None) -> dict[str, Any]:
        source_resolved = self.workspace.resolve_path(source)
        source_parent, source_name = self._parent_and_name(source)
        target, _target_name = self._validate_destination(destination_parent, source_name if name is None else name)
        if target == source:
            raise _public_error("same_destination", "The source and destination are the same", 409)
        if target.startswith(source_resolved.relative + "/"):
            raise _public_error("circular_move", "A directory cannot be moved inside itself", 409)
        self._require_missing(target)
        identity, kind = self._identity_and_type(source)
        count, affected, fingerprints = self._scan(source)
        for affected_path in affected:
            suffix = affected_path[len(source):]
            moved_path = target + suffix
            resolved = self.workspace.resolve_path(moved_path)
            if len(resolved.parts) > self.workspace.max_tree_depth + 1:
                raise _public_error("depth_limit", "The workspace depth limit was exceeded", 422)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._expire_locked()
            self._previews[token] = {
                "created": time.monotonic(), "action": "move", "source": source,
                "destination_parent": destination_parent, "destination": target,
                "identity": identity, "kind": kind, "affected": affected,
                "fingerprints": fingerprints,
            }
        return {"token": token, "source": source, "destination": target, "type": kind, "count": count}

    def apply_move(self, token: str) -> dict[str, Any]:
        preview = self._consume(token, "move")
        identity, kind = self._identity_and_type(preview["source"])
        if identity != preview["identity"] or kind != preview["kind"]:
            raise _public_error("operation_conflict", "The source changed before the operation", 409)
        if self._scan(preview["source"])[2] != preview["fingerprints"]:
            raise _public_error("operation_conflict", "The source changed before the operation", 409)
        source_parent, source_name = self._parent_and_name(preview["source"])
        destination_parent, destination_name = self._parent_and_name(preview["destination"])
        with self._lock, self._directory(source_parent) as source_fd, self._directory(destination_parent) as destination_fd:
            _rename_noreplace(source_fd, source_name, destination_fd, destination_name)
            moved = os.stat(destination_name, dir_fd=destination_fd, follow_symlinks=False)
            if (moved.st_dev, moved.st_ino) != identity:
                _rename_noreplace(destination_fd, destination_name, source_fd, source_name)
                raise _public_error("operation_conflict", "The source changed during the operation", 409)
        return {
            "old_path": preview["source"], "new_path": preview["destination"],
            "type": kind, "affected": preview["affected"],
        }

    def preview_delete(self, path: str) -> dict[str, Any]:
        identity, kind = self._identity_and_type(path)
        count, affected, fingerprints = self._scan(path)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._expire_locked()
            self._previews[token] = {
                "created": time.monotonic(), "action": "delete", "source": path,
                "identity": identity, "kind": kind, "affected": affected,
                "fingerprints": fingerprints,
            }
        return {"token": token, "path": path, "type": kind, "count": count}

    def apply_delete(self, token: str) -> dict[str, Any]:
        preview = self._consume(token, "delete")
        identity, kind = self._identity_and_type(preview["source"])
        if identity != preview["identity"] or kind != preview["kind"]:
            raise _public_error("operation_conflict", "The item changed before deletion", 409)
        if self._scan(preview["source"])[2] != preview["fingerprints"]:
            raise _public_error("operation_conflict", "The item changed before deletion", 409)
        parent, name = self._parent_and_name(preview["source"])
        quarantine = f".geram-workspace-delete-{secrets.token_hex(12)}"
        with self._lock, self._directory(parent) as parent_fd, self._directory("") as root_fd:
            _rename_noreplace(parent_fd, name, root_fd, quarantine)
            moved = os.stat(quarantine, dir_fd=root_fd, follow_symlinks=False)
            if (moved.st_dev, moved.st_ino) != identity:
                _rename_noreplace(root_fd, quarantine, parent_fd, name)
                raise _public_error("operation_conflict", "The item changed during deletion", 409)
            cleanup_pending = False
            try:
                self._remove_at(root_fd, quarantine, kind)
            except OSError:
                cleanup_pending = True
        return {
            "path": preview["source"], "type": kind, "affected": preview["affected"],
            "cleanup_pending": cleanup_pending,
        }

    def _remove_at(self, parent_fd: int, name: str, kind: str) -> None:
        if kind == "file":
            os.unlink(name, dir_fd=parent_fd)
            return
        directory_fd = os.open(name, self._directory_flags(), dir_fd=parent_fd)
        try:
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        raise OSError("unexpected symlink in quarantine")
                    child_kind = "directory" if entry.is_dir(follow_symlinks=False) else "file"
                    self._remove_at(directory_fd, entry.name, child_kind)
        finally:
            os.close(directory_fd)
        os.rmdir(name, dir_fd=parent_fd)

    def _consume(self, token: str, action: str) -> dict[str, Any]:
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", token):
            raise _public_error("invalid_operation_token", "The operation token is invalid", 422)
        with self._lock:
            self._expire_locked()
            preview = self._previews.pop(token, None)
        if preview is None or preview["action"] != action:
            raise _public_error("operation_not_found", "The operation preview was not found", 404)
        return preview

    def _expire_locked(self) -> None:
        now = time.monotonic()
        for token, preview in tuple(self._previews.items()):
            if now - preview["created"] > PREVIEW_TTL_SECONDS:
                self._previews.pop(token, None)
