"""Bounded local workspace access for the temporary text editor.

This module is the sole authority for path normalization, exclusions, text
classification, optimistic versions, and atomic replacement. Public errors
never contain absolute paths or file content.
"""

from __future__ import annotations

import codecs
import hashlib
import os
import secrets
import stat
import unicodedata

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterator, Sequence

from app.core.user_config import is_path_blocked


MAX_FILE_BYTES = 1024 * 1024
MAX_TREE_DEPTH = 6
MAX_TREE_ENTRIES = 1000
MAX_TREE_SCANNED_ENTRIES = 5000
TREE_SAMPLE_BYTES = 8192
TEMPORARY_PREFIX = ".geram-workspace-"

# Windows carece de la familia openat (dir_fd) que usa la ruta endurecida de
# abajo (read_file/tree/save_file). Detectamos el soporte real; si falta, el
# workspace usa una capa de acceso por RUTA (métodos *_fallback), que reusa
# toda la validación de resolve_path pero sin dir_fd. GERAM_FORCE_PATH_WORKSPACE=1
# fuerza esa capa aun en Linux, para poder probarla en desarrollo.
_DIR_FD_OK = (os.open in os.supports_dir_fd) and (
    os.environ.get("GERAM_FORCE_PATH_WORKSPACE") != "1"
)

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".claude",
        ".codex",
        ".cache",
        ".direnv",
        ".gradle",
        ".git",
        ".gnupg",
        ".kiosk-profile",
        ".local-data",
        ".mypy_cache",
        ".next",
        ".nox",
        ".npm",
        ".parcel-cache",
        ".pytest_cache",
        ".ruff_cache",
        ".ssh",
        ".svelte-kit",
        ".tox",
        ".turbo",
        ".venv",
        ".vite",
        "__pycache__",
        "bower_components",
        "build",
        "cache",
        "caches",
        "coverage",
        "credenciales",
        "dist",
        "env",
        "htmlcov",
        "logs",
        "node_modules",
        "out",
        "site-packages",
        "target",
        "vendor",
        "venv",
    }
)

EXCLUDED_FILE_SUFFIXES = frozenset(
    {
        ".7z",
        ".br",
        ".bz2",
        ".cab",
        ".db",
        ".db3",
        ".deb",
        ".dmg",
        ".duckdb",
        ".egg",
        ".gz",
        ".iso",
        ".jks",
        ".kdbx",
        ".key",
        ".keystore",
        ".lz",
        ".lz4",
        ".lzma",
        ".log",
        ".jsonl",
        ".mdb",
        ".pem",
        ".pfx",
        ".p12",
        ".ppk",
        ".rar",
        ".rdb",
        ".rpm",
        ".s3db",
        ".sqlite",
        ".sqlite2",
        ".sqlite3",
        ".tar",
        ".tgz",
        ".war",
        ".whl",
        ".xz",
        ".zip",
        ".zst",
    }
)

BINARY_FILE_SUFFIXES = frozenset(
    {
        ".a",
        ".avi",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dylib",
        ".eot",
        ".exe",
        ".gif",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".so",
        ".ttf",
        ".wav",
        ".webm",
        ".webp",
        ".woff",
        ".woff2",
    }
)


class WorkspaceError(RuntimeError):
    """A sanitized workspace failure safe for local API responses."""

    def __init__(self, code: str, message: str, status_code: int):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class ResolvedWorkspacePath:
    relative: str
    parts: tuple[str, ...]


def _public_error(code: str, message: str, status_code: int) -> WorkspaceError:
    return WorkspaceError(code, message, status_code)


def normalize_relative_path(raw_path: str) -> tuple[str, tuple[str, ...]]:
    """Return a canonical POSIX-style relative path or a sanitized error."""
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise _public_error("invalid_path", "A valid relative path is required", 400)
    if "\\" in raw_path:
        raise _public_error("invalid_path", "A valid relative path is required", 400)
    if PurePosixPath(raw_path).is_absolute() or PureWindowsPath(raw_path).is_absolute():
        # Ruta absoluta = intento de salir del workspace -> 403 Forbidden.
        raise _public_error("invalid_path", "Absolute paths are not allowed", 403)
    raw_parts = raw_path.split("/")
    if any(part == ".." for part in raw_parts):
        # Directory traversal (../) -> 403 Forbidden.
        raise _public_error("invalid_path", "Parent path components are not allowed", 403)
    parts = tuple(part for part in raw_parts if part not in {"", "."})
    if not parts:
        raise _public_error("invalid_path", "A valid relative path is required", 400)
    canonical = PurePosixPath(*parts).as_posix()
    return canonical, parts


def _excluded_name(name: str, *, directory: bool) -> bool:
    lowered = name.casefold()
    if lowered.startswith(TEMPORARY_PREFIX):
        return True
    if directory and lowered in EXCLUDED_DIRECTORY_NAMES:
        return True
    if lowered == ".env.example":
        return False
    if lowered == ".env" or lowered.startswith(".env."):
        return True
    if lowered in {".netrc", ".npmrc", ".pypirc"}:
        return True
    sensitive_prefixes = (
        "api-key",
        "api_key",
        "apikey",
        "credential.",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "private-key",
        "private_key",
        "secret.",
        "secrets",
    )
    if lowered in {"credential", "secret"} or lowered.startswith(sensitive_prefixes):
        return True
    if lowered.endswith(("-journal", "-wal", "-shm")):
        return True
    if ".log." in lowered or ".jsonl." in lowered:
        return True
    if lowered.endswith(tuple(EXCLUDED_FILE_SUFFIXES)):
        return True
    if lowered.endswith(".pid") or ".pid." in lowered:
        return True
    return False


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


class WorkspaceService:
    """List, read, and atomically replace text files inside one root."""

    def __init__(
        self,
        root: Path,
        *,
        protected_paths: Sequence[Path] = (),
        max_file_bytes: int = MAX_FILE_BYTES,
        max_tree_depth: int = MAX_TREE_DEPTH,
        max_tree_entries: int = MAX_TREE_ENTRIES,
        max_tree_scanned_entries: int = MAX_TREE_SCANNED_ENTRIES,
    ):
        try:
            self.root = root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise _public_error(
                "workspace_unavailable",
                "The local workspace is unavailable",
                503,
            ) from None
        if not self.root.is_dir():
            raise _public_error(
                "workspace_unavailable",
                "The local workspace is unavailable",
                503,
            )
        self.protected_paths = tuple(path.resolve(strict=False) for path in protected_paths)
        self.max_file_bytes = max_file_bytes
        self.max_tree_depth = max_tree_depth
        self.max_tree_entries = max_tree_entries
        self.max_tree_scanned_entries = max_tree_scanned_entries

    def _is_protected(self, candidate: Path) -> bool:
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            return True
        return any(
            resolved == protected or _path_is_within(resolved, protected)
            for protected in self.protected_paths
        )

    def _check_exclusions(self, parts: Sequence[str]) -> None:
        for index, part in enumerate(parts):
            is_final = index == len(parts) - 1
            if _excluded_name(part, directory=True) or (
                is_final and _excluded_name(part, directory=False)
            ):
                raise _public_error(
                    "protected_path",
                    "The requested path is not available",
                    403,
                )

    def _parent_identity_matches(
        self,
        parent_fd: int,
        resolved: ResolvedWorkspacePath,
    ) -> bool:
        expected_parent = self.root.joinpath(*resolved.parts[:-1])
        try:
            expected_status = os.stat(expected_parent, follow_symlinks=False)
            descriptor_status = os.fstat(parent_fd)
        except OSError:
            return False
        return (
            stat.S_ISDIR(expected_status.st_mode)
            and expected_status.st_dev == descriptor_status.st_dev
            and expected_status.st_ino == descriptor_status.st_ino
        )

    def resolve_path(self, raw_path: str) -> ResolvedWorkspacePath:
        """Resolve and validate a path without returning it to the client."""
        relative, parts = normalize_relative_path(raw_path)
        self._check_exclusions(parts)
        candidate = self.root.joinpath(*parts)
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            raise _public_error("invalid_path", "The requested path is invalid", 400) from None
        if not _path_is_within(resolved, self.root):
            raise _public_error(
                "path_escape",
                "The requested path is outside the workspace",
                403,
            )
        current = self.root
        for part in parts:
            current = current / part
            try:
                if current.is_symlink():
                    raise _public_error(
                        "symlink_not_allowed",
                        "Symbolic links are not editable",
                        403,
                    )
            except OSError:
                raise _public_error("invalid_path", "The requested path is invalid", 400) from None
        if self._is_protected(resolved):
            raise _public_error(
                "protected_path",
                "The requested path is not available",
                403,
            )
        return ResolvedWorkspacePath(relative, parts)

    @contextmanager
    def _open_parent(self, resolved: ResolvedWorkspacePath) -> Iterator[tuple[int, str]]:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_CLOEXEC"):
            directory_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        descriptors: list[int] = []
        try:
            current_fd = os.open(self.root, directory_flags)
            descriptors.append(current_fd)
            for part in resolved.parts[:-1]:
                current_fd = os.open(part, directory_flags, dir_fd=current_fd)
                descriptors.append(current_fd)
            if not self._parent_identity_matches(current_fd, resolved):
                raise _public_error(
                    "path_changed",
                    "The requested path changed during access",
                    409,
                )
            yield current_fd, resolved.parts[-1]
        except FileNotFoundError:
            raise _public_error("not_found", "The requested file does not exist", 404) from None
        except NotADirectoryError:
            raise _public_error("invalid_path", "The requested path is invalid", 400) from None
        except OSError:
            raise _public_error("workspace_unavailable", "The local file is unavailable", 403) from None
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _open_file(self, parent_fd: int, name: str) -> int:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            return os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            raise _public_error("not_found", "The requested file does not exist", 404) from None
        except OSError:
            raise _public_error("workspace_unavailable", "The local file is unavailable", 403) from None

    def _read_descriptor(self, descriptor: int) -> tuple[bytes, os.stat_result]:
        try:
            file_status = os.fstat(descriptor)
            if not stat.S_ISREG(file_status.st_mode):
                raise _public_error("not_a_file", "The requested path is not a file", 400)
            if file_status.st_size > self.max_file_bytes:
                raise _public_error("file_too_large", "The file exceeds the editing limit", 413)
            chunks: list[bytes] = []
            remaining = self.max_file_bytes + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
        except WorkspaceError:
            raise
        except OSError:
            raise _public_error("workspace_unavailable", "The local file is unavailable", 403) from None
        if len(data) > self.max_file_bytes:
            raise _public_error("file_too_large", "The file exceeds the editing limit", 413)
        return data, file_status

    @staticmethod
    def _decode_text(data: bytes) -> str:
        if b"\x00" in data:
            raise _public_error("binary_file", "Binary files cannot be edited", 415)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise _public_error("binary_file", "Binary files cannot be edited", 415) from None
        if any(
            unicodedata.category(character) == "Cc"
            and character not in {"\t", "\n", "\r", "\f"}
            for character in text
        ):
            raise _public_error("binary_file", "Binary files cannot be edited", 415)
        return text

    @staticmethod
    def _version(data: bytes) -> str:
        return hashlib.sha256(b"geram-workspace-v1\0" + data).hexdigest()

    @staticmethod
    def _reject_hardlink(file_status: os.stat_result) -> None:
        if stat.S_ISREG(file_status.st_mode) and file_status.st_nlink != 1:
            raise _public_error(
                "protected_path",
                "The requested path is not available",
                403,
            )

    def read_file(self, raw_path: str) -> dict[str, str]:
        if not _DIR_FD_OK:
            return self._read_file_fallback(raw_path)
        resolved = self.resolve_path(raw_path)
        if _excluded_name(resolved.parts[-1], directory=False):
            raise _public_error("protected_path", "The requested path is not available", 403)
        # Privacy controls (v3, Paso 2): rutas/nombres en blocked_paths de
        # .geram-config.json nunca se sirven, ni a agentes ni al editor.
        if is_path_blocked(resolved.relative, resolved.parts[-1]):
            raise _public_error("protected_path", "The requested path is not available", 403)
        if Path(resolved.parts[-1]).suffix.casefold() in BINARY_FILE_SUFFIXES:
            raise _public_error("binary_file", "Binary files cannot be edited", 415)
        with self._open_parent(resolved) as (parent_fd, name):
            descriptor = self._open_file(parent_fd, name)
            try:
                self._reject_hardlink(os.fstat(descriptor))
                data, _file_status = self._read_descriptor(descriptor)
            finally:
                os.close(descriptor)
        return {
            "path": resolved.relative,
            "content": self._decode_text(data),
            "version": self._version(data),
        }

    def _tree_file_editable(self, parent_fd: int, name: str) -> bool:
        if Path(name).suffix.casefold() in BINARY_FILE_SUFFIXES:
            return False
        descriptor = -1
        try:
            descriptor = self._open_file(parent_fd, name)
            file_status = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_status.st_mode)
                or file_status.st_nlink != 1
                or file_status.st_size > self.max_file_bytes
            ):
                return False
            sample = os.read(descriptor, TREE_SAMPLE_BYTES)
        except (OSError, ValueError, WorkspaceError):
            return False
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if b"\x00" in sample:
            return False
        try:
            decoder = codecs.getincrementaldecoder("utf-8")()
            decoded_sample = decoder.decode(sample, final=False)
        except UnicodeDecodeError:
            return False
        return not any(
            unicodedata.category(character) == "Cc"
            and character not in {"\t", "\n", "\r", "\f"}
            for character in decoded_sample
        )

    def tree(self) -> dict[str, object]:
        if not _DIR_FD_OK:
            return self._tree_fallback()
        entries: list[dict[str, object]] = []
        output_truncated = False
        scan_truncated = False
        scanned_entries = 0
        depth_limited = False

        directory_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_CLOEXEC"):
            directory_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW

        def add_directory(directory_fd: int, relative_parts: tuple[str, ...], depth: int) -> None:
            nonlocal output_truncated, scan_truncated, scanned_entries, depth_limited
            try:
                with os.scandir(directory_fd) as scanner:
                    scanned = []
                    for entry in scanner:
                        if scanned_entries >= self.max_tree_scanned_entries:
                            scan_truncated = True
                            break
                        scanned_entries += 1
                        scanned.append(entry)
            except (OSError, PermissionError):
                return
            directories: list[os.DirEntry[str]] = []
            files: list[os.DirEntry[str]] = []
            for entry in scanned:
                if entry.is_symlink():
                    continue
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                if not is_directory and not is_file:
                    continue
                if _excluded_name(entry.name, directory=True) or (
                    is_file and _excluded_name(entry.name, directory=False)
                ):
                    continue
                candidate = self.root.joinpath(*relative_parts, entry.name)
                if self._is_protected(candidate):
                    continue
                (directories if is_directory else files).append(entry)

            directories.sort(key=lambda item: item.name.casefold())
            files.sort(key=lambda item: item.name.casefold())
            for entry in directories:
                if len(entries) >= self.max_tree_entries:
                    output_truncated = True
                    return
                child_parts = relative_parts + (entry.name,)
                entries.append(
                    {
                        "path": PurePosixPath(*child_parts).as_posix(),
                        "name": entry.name,
                        "type": "directory",
                        "depth": depth,
                    }
                )
                if depth < self.max_tree_depth and not scan_truncated:
                    child_fd = -1
                    try:
                        child_fd = os.open(entry.name, directory_flags, dir_fd=directory_fd)
                        add_directory(child_fd, child_parts, depth + 1)
                    except OSError:
                        pass
                    finally:
                        if child_fd >= 0:
                            os.close(child_fd)
                else:
                    depth_limited = True
                if output_truncated:
                    return
            for entry in files:
                if len(entries) >= self.max_tree_entries:
                    output_truncated = True
                    return
                child_parts = relative_parts + (entry.name,)
                entries.append(
                    {
                        "path": PurePosixPath(*child_parts).as_posix(),
                        "name": entry.name,
                        "type": "file",
                        "depth": depth,
                        "editable": self._tree_file_editable(directory_fd, entry.name),
                    }
                )

        root_fd = -1
        try:
            root_fd = os.open(self.root, directory_flags)
            add_directory(root_fd, (), 1)
        except OSError:
            raise _public_error(
                "workspace_unavailable",
                "The local workspace is unavailable",
                503,
            ) from None
        finally:
            if root_fd >= 0:
                os.close(root_fd)
        return {
            "entries": entries,
            "truncated": output_truncated or scan_truncated,
            "depth_limited": depth_limited,
            "limits": {
                "max_depth": self.max_tree_depth,
                "max_entries": self.max_tree_entries,
                "max_file_bytes": self.max_file_bytes,
            },
        }

    @staticmethod
    def _write_all(descriptor: int, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written == 0:
                raise OSError("incomplete local write")
            remaining = remaining[written:]

    def save_file(self, raw_path: str, content: str, base_version: str) -> dict[str, str]:
        if not isinstance(content, str) or not isinstance(base_version, str):
            raise _public_error("invalid_request", "The save request is invalid", 422)
        if not _DIR_FD_OK:
            return self._save_file_fallback(raw_path, content, base_version)
        resolved = self.resolve_path(raw_path)
        if Path(resolved.parts[-1]).suffix.casefold() in BINARY_FILE_SUFFIXES:
            raise _public_error("binary_file", "Binary files cannot be edited", 415)
        try:
            encoded_content = content.encode("utf-8")
        except UnicodeEncodeError:
            raise _public_error("invalid_request", "The save request is invalid", 422) from None
        if len(encoded_content) > self.max_file_bytes:
            raise _public_error("file_too_large", "The file exceeds the editing limit", 413)

        with self._open_parent(resolved) as (parent_fd, name):
            original_fd = self._open_file(parent_fd, name)
            try:
                self._reject_hardlink(os.fstat(original_fd))
                original_data, original_status = self._read_descriptor(original_fd)
            finally:
                os.close(original_fd)
            self._decode_text(original_data)
            if self._version(original_data) != base_version:
                raise _public_error(
                    "version_conflict",
                    "The file changed after it was opened",
                    409,
                )

            output = (
                codecs.BOM_UTF8 + encoded_content
                if original_data.startswith(codecs.BOM_UTF8)
                else encoded_content
            )
            temporary_name = f"{TEMPORARY_PREFIX}{secrets.token_hex(12)}.tmp"
            temporary_fd = -1
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_CLOEXEC"):
                    flags |= os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                temporary_fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
                self._write_all(temporary_fd, output)
                os.fsync(temporary_fd)

                current_status = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if (
                    not self._parent_identity_matches(parent_fd, resolved)
                    or not stat.S_ISREG(current_status.st_mode)
                    or current_status.st_nlink != 1
                    or current_status.st_dev != original_status.st_dev
                    or current_status.st_ino != original_status.st_ino
                ):
                    raise _public_error(
                        "version_conflict",
                        "The file changed after it was opened",
                        409,
                    )
                current_fd = self._open_file(parent_fd, name)
                try:
                    current_data, _current_status = self._read_descriptor(current_fd)
                finally:
                    os.close(current_fd)
                if self._version(current_data) != base_version:
                    raise _public_error(
                        "version_conflict",
                        "The file changed after it was opened",
                        409,
                    )

                os.replace(
                    temporary_name,
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
                temporary_name = ""
                os.fchmod(temporary_fd, stat.S_IMODE(original_status.st_mode))
                os.fsync(temporary_fd)
                os.close(temporary_fd)
                temporary_fd = -1
                os.fsync(parent_fd)
            except WorkspaceError:
                raise
            except OSError:
                raise _public_error("save_failed", "The file could not be saved", 500) from None
            finally:
                if temporary_fd >= 0:
                    os.close(temporary_fd)
                if temporary_name:
                    try:
                        os.unlink(temporary_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass

        return {"path": resolved.relative, "version": self._version(output)}

    def save_files_atomically(
        self,
        edits: Sequence[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Preflight and replace existing files with compensating rollback.

        POSIX has no cross-file rename transaction. This method therefore
        validates every base before the first write, uses ``save_file`` for
        each descriptor-safe replacement, and restores every completed write
        if a later replacement fails.
        """
        if not isinstance(edits, Sequence) or isinstance(edits, (str, bytes)) or not edits:
            raise _public_error("invalid_request", "The save request is invalid", 422)
        required = {"path", "content", "base_version"}
        allowed = required | {"operation"}
        normalized: list[dict[str, str]] = []
        originals: dict[str, dict[str, str]] = {}
        seen: set[str] = set()
        for edit in edits:
            if (
                not isinstance(edit, dict)
                or not required.issubset(edit)
                or (set(edit) - allowed)
            ):
                raise _public_error("invalid_request", "The save request is invalid", 422)
            path = edit.get("path")
            content = edit.get("content")
            base_version = edit.get("base_version")
            operation = edit.get("operation", "replace_existing_file")
            if operation not in ("replace_existing_file", "create_new_file"):
                raise _public_error("invalid_request", "The save request is invalid", 422)
            if not all(isinstance(value, str) for value in (path, content, base_version)):
                raise _public_error("invalid_request", "The save request is invalid", 422)
            try:
                encoded_content = content.encode("utf-8")
            except UnicodeEncodeError:
                raise _public_error("invalid_request", "The save request is invalid", 422) from None
            if len(encoded_content) > self.max_file_bytes:
                raise _public_error("file_too_large", "The file exceeds the editing limit", 413)
            if operation == "create_new_file":
                # A new file has no base to compare; it must not already exist.
                if base_version != "":
                    raise _public_error("invalid_request", "The save request is invalid", 422)
                resolved = self.resolve_path(path)
                canonical = resolved.relative
                if canonical in seen:
                    raise _public_error("invalid_request", "The save request is invalid", 422)
                seen.add(canonical)
                if self._abs_path(resolved).exists():
                    raise _public_error("file_exists", "A file already exists at that path", 409)
                normalized.append({
                    "path": canonical,
                    "content": content,
                    "base_version": "",
                    "operation": "create_new_file",
                })
            else:
                current = self.read_file(path)
                if current["path"] in seen:
                    raise _public_error("invalid_request", "The save request is invalid", 422)
                seen.add(current["path"])
                if current["version"] != base_version:
                    raise _public_error(
                        "version_conflict",
                        "A file changed before the operation could be applied",
                        409,
                    )
                normalized.append({
                    "path": current["path"],
                    "content": content,
                    "base_version": base_version,
                    "operation": "replace_existing_file",
                })
                originals[current["path"]] = current

        applied: list[dict[str, str]] = []
        try:
            for edit in normalized:
                if edit["operation"] == "create_new_file":
                    result = self.create_file(edit["path"], edit["content"])
                else:
                    result = self.save_file(
                        edit["path"],
                        edit["content"],
                        edit["base_version"],
                    )
                applied.append({**result, "operation": edit["operation"]})
        except Exception as error:
            rollback_failed = False
            for result in reversed(applied):
                try:
                    if result.get("operation") == "create_new_file":
                        # Undo a create by removing the file we just wrote.
                        os.unlink(self._abs_path(self.resolve_path(result["path"])))
                    else:
                        original = originals[result["path"]]
                        self.save_file(
                            original["path"],
                            original["content"],
                            result["version"],
                        )
                except Exception:
                    rollback_failed = True
            if rollback_failed:
                raise _public_error(
                    "atomic_rollback_failed",
                    "The multi-file operation could not be restored safely",
                    500,
                ) from None
            if isinstance(error, WorkspaceError):
                raise
            raise _public_error(
                "atomic_save_failed",
                "The multi-file operation could not be applied",
                500,
            ) from None
        return [{"path": result["path"], "version": result["version"]} for result in applied]

    def create_file(self, raw_path: str, content: str) -> dict[str, str]:
        """Create a NEW text file, failing if it already exists.

        Shares resolve_path validation (rejects symlinks per component,
        out-of-root, excluded and protected paths) with every other write.
        Uses O_CREAT|O_EXCL|O_NOFOLLOW so the create is atomic, never follows a
        symlink, and never overwrites existing content. Missing parent
        directories are created within the workspace root.
        """
        if not isinstance(content, str):
            raise _public_error("invalid_request", "The save request is invalid", 422)
        try:
            encoded = content.encode("utf-8")
        except UnicodeEncodeError:
            raise _public_error("invalid_request", "The save request is invalid", 422) from None
        if len(encoded) > self.max_file_bytes:
            raise _public_error("file_too_large", "The file exceeds the editing limit", 413)
        resolved = self.resolve_path(raw_path)
        abs_path = self._abs_path(resolved)
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise _public_error("save_failed", "The file could not be created", 500) from None
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        for optional in ("O_CLOEXEC", "O_NOFOLLOW", "O_BINARY"):
            if hasattr(os, optional):
                flags |= getattr(os, optional)
        try:
            descriptor = os.open(str(abs_path), flags, 0o600)
        except FileExistsError:
            raise _public_error("file_exists", "A file already exists at that path", 409) from None
        except OSError:
            raise _public_error("save_failed", "The file could not be created", 500) from None
        try:
            self._write_all(descriptor, encoded)
            os.fsync(descriptor)
        except OSError:
            try:
                os.unlink(str(abs_path))
            except OSError:
                pass
            raise _public_error("save_failed", "The file could not be created", 500) from None
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
        return {"path": resolved.relative, "version": self._version(encoded)}

    def create_binary_file(self, raw_path: str, data: bytes, max_bytes: int) -> dict[str, object]:
        """Crea un archivo NUEVO con contenido binario (subidas del explorador).

        Gemelo de create_file para datos que no son texto: comparte
        resolve_path (symlinks por componente, fuera de root, rutas excluidas
        y protegidas) y el mismo O_CREAT|O_EXCL|O_NOFOLLOW, así que tampoco
        sigue enlaces ni pisa nada existente. Sólo cambia que no se codifica
        a UTF-8 y que el límite de tamaño lo pone quien llama: subir un PNG
        de 4 MB es legítimo aunque el editor no pueda abrirlo.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise _public_error("invalid_request", "The upload request is invalid", 422)
        data = bytes(data)
        if len(data) > max_bytes:
            raise _public_error("file_too_large", "The file exceeds the upload limit", 413)
        resolved = self.resolve_path(raw_path)
        abs_path = self._abs_path(resolved)
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise _public_error("upload_failed", "The file could not be created", 500) from None
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        for optional in ("O_CLOEXEC", "O_NOFOLLOW", "O_BINARY"):
            if hasattr(os, optional):
                flags |= getattr(os, optional)
        try:
            descriptor = os.open(str(abs_path), flags, 0o600)
        except FileExistsError:
            raise _public_error("file_exists", "A file already exists at that path", 409) from None
        except OSError:
            raise _public_error("upload_failed", "The file could not be created", 500) from None
        try:
            self._write_all(descriptor, data)
            os.fsync(descriptor)
        except OSError:
            try:
                os.unlink(str(abs_path))
            except OSError:
                pass
            raise _public_error("upload_failed", "The file could not be created", 500) from None
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
        # Mismo criterio que _tree_file_editable: extensión binaria conocida,
        # tamaño por encima del límite de edición, o bytes nulos -> no editable.
        editable = (
            Path(resolved.parts[-1]).suffix.casefold() not in BINARY_FILE_SUFFIXES
            and len(data) <= self.max_file_bytes
            and b"\x00" not in data[:TREE_SAMPLE_BYTES]
        )
        return {"path": resolved.relative, "size": len(data), "editable": editable}

    # ------------------------------------------------------------------ #
    # Capa de acceso por RUTA — Windows / plataformas sin openat/dir_fd.
    #
    # Reusa TODA la validación de resolve_path (rechaza symlinks por componente
    # y rutas fuera de root) y los mismos checks de versión/tamaño/binario; solo
    # cambia el acceso a disco de "relativo a un fd de directorio" a "por ruta
    # absoluta". Pierde el endurecimiento anti-TOCTOU de openat (aceptable en un
    # equipo local mono-usuario; Linux conserva la ruta endurecida). En Windows
    # O_BINARY es obligatorio para no traducir CRLF ni cortar en Ctrl-Z (0x1A).
    # save_files_atomically no necesita variante: orquesta read_file/save_file.
    # ------------------------------------------------------------------ #
    def _abs_path(self, resolved: ResolvedWorkspacePath) -> Path:
        return self.root.joinpath(*resolved.parts)

    def _read_path(self, abs_path: Path) -> tuple[bytes, os.stat_result]:
        try:
            link_status = os.lstat(abs_path)
        except FileNotFoundError:
            raise _public_error("not_found", "The requested file does not exist", 404) from None
        except OSError:
            raise _public_error("workspace_unavailable", "The local file is unavailable", 403) from None
        if stat.S_ISLNK(link_status.st_mode):
            raise _public_error("symlink_not_allowed", "Symbolic links are not editable", 403)
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):  # no bloquear abriendo un FIFO/pipe sin escritor
            flags |= os.O_NONBLOCK
        try:
            descriptor = os.open(str(abs_path), flags)
        except FileNotFoundError:
            raise _public_error("not_found", "The requested file does not exist", 404) from None
        except OSError:
            raise _public_error("workspace_unavailable", "The local file is unavailable", 403) from None
        try:
            self._reject_hardlink(os.fstat(descriptor))
            data, file_status = self._read_descriptor(descriptor)
        finally:
            os.close(descriptor)
        return data, file_status

    def _read_file_fallback(self, raw_path: str) -> dict[str, str]:
        resolved = self.resolve_path(raw_path)
        if _excluded_name(resolved.parts[-1], directory=False):
            raise _public_error("protected_path", "The requested path is not available", 403)
        if is_path_blocked(resolved.relative, resolved.parts[-1]):
            raise _public_error("protected_path", "The requested path is not available", 403)
        if Path(resolved.parts[-1]).suffix.casefold() in BINARY_FILE_SUFFIXES:
            raise _public_error("binary_file", "Binary files cannot be edited", 415)
        data, _status = self._read_path(self._abs_path(resolved))
        return {
            "path": resolved.relative,
            "content": self._decode_text(data),
            "version": self._version(data),
        }

    def _save_file_fallback(self, raw_path: str, content: str, base_version: str) -> dict[str, str]:
        resolved = self.resolve_path(raw_path)
        if Path(resolved.parts[-1]).suffix.casefold() in BINARY_FILE_SUFFIXES:
            raise _public_error("binary_file", "Binary files cannot be edited", 415)
        try:
            encoded_content = content.encode("utf-8")
        except UnicodeEncodeError:
            raise _public_error("invalid_request", "The save request is invalid", 422) from None
        if len(encoded_content) > self.max_file_bytes:
            raise _public_error("file_too_large", "The file exceeds the editing limit", 413)

        abs_path = self._abs_path(resolved)
        original_data, original_status = self._read_path(abs_path)
        self._decode_text(original_data)
        if self._version(original_data) != base_version:
            raise _public_error("version_conflict", "The file changed after it was opened", 409)

        output = (
            codecs.BOM_UTF8 + encoded_content
            if original_data.startswith(codecs.BOM_UTF8)
            else encoded_content
        )
        temporary_path = abs_path.parent / f"{TEMPORARY_PREFIX}{secrets.token_hex(12)}.tmp"
        temporary_fd = -1
        created = False
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            temporary_fd = os.open(str(temporary_path), flags, 0o600)
            created = True
            self._write_all(temporary_fd, output)
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = -1

            # Detecta cambios del destino entre abrir y reemplazar (sin dir_fd:
            # re-stat + re-hash del contenido, que es el detector más fuerte).
            current_status = os.stat(abs_path, follow_symlinks=False)
            if not stat.S_ISREG(current_status.st_mode) or current_status.st_nlink != 1:
                raise _public_error("version_conflict", "The file changed after it was opened", 409)
            current_data, _current = self._read_path(abs_path)
            if self._version(current_data) != base_version:
                raise _public_error("version_conflict", "The file changed after it was opened", 409)

            os.replace(str(temporary_path), str(abs_path))  # atómico en Windows y POSIX
            created = False
            # El temp se mantuvo 0600 durante toda la ventana; recién ahora, ya
            # en su sitio, fija el modo original (en Windows: el bit solo-lectura).
            try:
                os.chmod(str(abs_path), stat.S_IMODE(original_status.st_mode))
            except OSError:
                pass
        except WorkspaceError:
            raise
        except OSError:
            raise _public_error("save_failed", "The file could not be saved", 500) from None
        finally:
            if temporary_fd >= 0:
                os.close(temporary_fd)
            if created:
                try:
                    os.unlink(str(temporary_path))
                except OSError:
                    pass
        return {"path": resolved.relative, "version": self._version(output)}

    def _tree_file_editable_path(self, abs_path: Path) -> bool:
        if abs_path.suffix.casefold() in BINARY_FILE_SUFFIXES:
            return False
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):  # no bloquear abriendo un FIFO/pipe sin escritor
            flags |= os.O_NONBLOCK
        descriptor = -1
        try:
            descriptor = os.open(str(abs_path), flags)
            file_status = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_status.st_mode)
                or file_status.st_nlink != 1
                or file_status.st_size > self.max_file_bytes
            ):
                return False
            sample = os.read(descriptor, TREE_SAMPLE_BYTES)
        except (OSError, ValueError, WorkspaceError):
            return False
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if b"\x00" in sample:
            return False
        try:
            decoder = codecs.getincrementaldecoder("utf-8")()
            decoded_sample = decoder.decode(sample, final=False)
        except UnicodeDecodeError:
            return False
        return not any(
            unicodedata.category(character) == "Cc"
            and character not in {"\t", "\n", "\r", "\f"}
            for character in decoded_sample
        )

    def _tree_fallback(self) -> dict[str, object]:
        entries: list[dict[str, object]] = []
        output_truncated = False
        scan_truncated = False
        scanned_entries = 0
        depth_limited = False

        def add_directory(directory_abs: Path, relative_parts: tuple[str, ...], depth: int) -> None:
            nonlocal output_truncated, scan_truncated, scanned_entries, depth_limited
            try:
                with os.scandir(directory_abs) as scanner:
                    scanned = []
                    for entry in scanner:
                        if scanned_entries >= self.max_tree_scanned_entries:
                            scan_truncated = True
                            break
                        scanned_entries += 1
                        scanned.append(entry)
            except (OSError, PermissionError):
                return
            directories: list[os.DirEntry[str]] = []
            files: list[os.DirEntry[str]] = []
            for entry in scanned:
                if entry.is_symlink():
                    continue
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                if not is_directory and not is_file:
                    continue
                if _excluded_name(entry.name, directory=True) or (
                    is_file and _excluded_name(entry.name, directory=False)
                ):
                    continue
                candidate = self.root.joinpath(*relative_parts, entry.name)
                if self._is_protected(candidate):
                    continue
                (directories if is_directory else files).append(entry)

            directories.sort(key=lambda item: item.name.casefold())
            files.sort(key=lambda item: item.name.casefold())
            for entry in directories:
                if len(entries) >= self.max_tree_entries:
                    output_truncated = True
                    return
                child_parts = relative_parts + (entry.name,)
                entries.append({
                    "path": PurePosixPath(*child_parts).as_posix(),
                    "name": entry.name,
                    "type": "directory",
                    "depth": depth,
                })
                if depth < self.max_tree_depth and not scan_truncated:
                    add_directory(Path(entry.path), child_parts, depth + 1)
                else:
                    depth_limited = True
                if output_truncated:
                    return
            for entry in files:
                if len(entries) >= self.max_tree_entries:
                    output_truncated = True
                    return
                child_parts = relative_parts + (entry.name,)
                entries.append({
                    "path": PurePosixPath(*child_parts).as_posix(),
                    "name": entry.name,
                    "type": "file",
                    "depth": depth,
                    "editable": self._tree_file_editable_path(Path(entry.path)),
                })

        try:
            add_directory(self.root, (), 1)
        except OSError:
            raise _public_error("workspace_unavailable", "The local workspace is unavailable", 503) from None
        return {
            "entries": entries,
            "truncated": output_truncated or scan_truncated,
            "depth_limited": depth_limited,
            "limits": {
                "max_depth": self.max_tree_depth,
                "max_entries": self.max_tree_entries,
                "max_file_bytes": self.max_file_bytes,
            },
        }
