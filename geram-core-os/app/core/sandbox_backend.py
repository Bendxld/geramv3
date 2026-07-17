"""Mandatory Bubblewrap backend for closed, local test execution."""
from dataclasses import dataclass
import os
from pathlib import Path

from app.core.sandbox_guard import is_sensitive_workspace_path


_TRUSTED_BWRAP_PATHS = (Path("/usr/bin/bwrap"), Path("/bin/bwrap"))
_REQUIRED_PREFIX_FLAGS = frozenset({
    "--cap-drop",
    "--chdir",
    "--clearenv",
    "--die-with-parent",
    "--disable-userns",
    "--proc",
    "--ro-bind",
    "--tmpfs",
    "--unshare-all",
})

class SandboxUnavailableError(RuntimeError):
    pass

@dataclass(frozen=True)
class SandboxBackend:
    name: str
    executable: str


def _trusted_bwrap() -> Path | None:
    trusted_resolved: set[Path] = set()
    for candidate in _TRUSTED_BWRAP_PATHS:
        try:
            trusted_resolved.add(candidate.resolve(strict=True))
        except OSError:
            continue
    for candidate in _TRUSTED_BWRAP_PATHS:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved in trusted_resolved and resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def detect_sandbox_backend() -> SandboxBackend:
    executable = _trusted_bwrap()
    if executable is None:
        raise SandboxUnavailableError("No enforced sandbox backend is available.")
    return SandboxBackend("bubblewrap", str(executable))


def _resolved_directory(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise SandboxUnavailableError("Sandbox paths are unavailable.") from None
    if not resolved.is_dir():
        raise SandboxUnavailableError("Sandbox paths are unavailable.")
    return resolved


def _sensitive_mounts(workspace: Path) -> list[str]:
    """Overlay sensitive workspace entries without following project symlinks."""
    entries: list[tuple[Path, Path, bool, tuple[int, int] | None]] = []
    sensitive_file_identities: set[tuple[int, int]] = set()
    pending = [workspace]
    try:
        while pending:
            directory = pending.pop()
            for entry in directory.iterdir():
                relative = entry.relative_to(workspace)
                is_directory = entry.is_dir() and not entry.is_symlink()
                identity = None
                if not is_directory and not entry.is_symlink():
                    stat = entry.stat(follow_symlinks=False)
                    identity = (stat.st_dev, stat.st_ino)
                sensitive = is_sensitive_workspace_path(relative)
                entries.append((entry, relative, is_directory, identity))
                if sensitive and identity is not None:
                    sensitive_file_identities.add(identity)
                if sensitive:
                    continue
                if is_directory:
                    pending.append(entry)
    except (OSError, RuntimeError, ValueError):
        raise SandboxUnavailableError("Sensitive workspace paths could not be isolated.") from None

    arguments: list[str] = []
    for _entry, relative, is_directory, identity in entries:
        if not is_sensitive_workspace_path(relative) and identity not in sensitive_file_identities:
            continue
        destination = (Path("/workspace") / relative).as_posix()
        if is_directory:
            arguments.extend(("--tmpfs", destination, "--remount-ro", destination))
        else:
            arguments.extend(("--ro-bind", "/dev/null", destination))
    return arguments


def is_enforced_sandbox_prefix(prefix: list[str]) -> bool:
    """Validate the minimum structure that prevents an implicit host fallback."""
    if not prefix or prefix[-1] != "--" or "--share-net" in prefix:
        return False
    try:
        executable = Path(prefix[0]).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    trusted = _trusted_bwrap()
    if trusted is None or executable != trusted:
        return False
    if not _REQUIRED_PREFIX_FLAGS.issubset(prefix):
        return False
    try:
        workspace_index = prefix.index("/workspace")
    except ValueError:
        return False
    return workspace_index > 1 and prefix[workspace_index - 2] == "--ro-bind"

def build_sandbox_prefix(backend: SandboxBackend, workspace: Path, runtime_root: Path) -> list[str]:
    trusted = _trusted_bwrap()
    try:
        executable = Path(backend.executable).resolve(strict=True)
    except (AttributeError, OSError, RuntimeError, TypeError):
        raise SandboxUnavailableError("Sandbox backend is invalid.") from None
    if backend.name != "bubblewrap" or trusted is None or executable != trusted:
        raise SandboxUnavailableError("Sandbox backend is invalid.")
    workspace = _resolved_directory(workspace)
    _resolved_directory(runtime_root)
    prefix = [
        str(executable),
        "--die-with-parent",
        "--unshare-all",
        "--unshare-user",
        "--disable-userns",
        "--cap-drop", "ALL",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "PYTHONUNBUFFERED", "1",
        "--setenv", "PYTHONPATH", "/opt/geram",
        "--setenv", "HOME", "/tmp/home",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", str(Path(__file__).resolve().parents[1]), "/opt/geram/app",
        "--ro-bind", str(workspace), "/workspace",
    ]
    prefix.extend(_sensitive_mounts(workspace))
    prefix.extend((
        "--tmpfs", "/tmp",
        "--dir", "/tmp/home",
        "--proc", "/proc",
        "--dev", "/dev",
        "--chdir", "/workspace",
        "--",
    ))
    if not is_enforced_sandbox_prefix(prefix):
        raise SandboxUnavailableError("Sandbox prefix is incomplete.")
    return prefix
