"""Fail-closed policy for the closed set of synthetic watcher tasks."""
from dataclasses import dataclass
from pathlib import Path
import math
import os
import re
import secrets
import sys
import unicodedata

from app.core.config import settings

SANDBOX_POLICY_VERSION = 1
_ROOT = Path(__file__).resolve().parents[2]
_BAD = re.compile(r"(?:\x00|\r|\n|https?://|\$\{|\b(?:bash|sh|sudo|curl|wget|ssh|nc)\b)", re.I)
_SENSITIVE_DIRECTORY_NAMES = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
})
_SENSITIVE_FILE_NAMES = frozenset({
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "secrets.json",
})
_SENSITIVE_FILE_SUFFIXES = (
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".db3",
    ".db3-journal",
    ".db3-shm",
    ".db3-wal",
    ".key",
    ".keystore",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".sqlite-journal",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3-journal",
    ".sqlite3-shm",
    ".sqlite3-wal",
)
_TRUSTED_NODE_PATHS = (Path("/usr/bin/node"), Path("/bin/node"))

@dataclass(frozen=True)
class ExecutionSpec:
    purpose: str
    executable_id: str
    args: tuple[str, ...] = ()
    cwd: str = "."
    timeout_seconds: float = 5.0
    environment_profile: str = "synthetic_minimal"
    network_policy: str = "deny"
    filesystem_policy: str = "read_only_workspace_metadata"
    resource_profile: str = "small"
    requested_by: str = "terminal_watcher"

@dataclass(frozen=True)
class Decision:
    allowed: bool
    decision_id: str
    policy_version: int
    reason_code: str
    message: str
    spec: ExecutionSpec | None = None

_PURPOSES = {"stdout", "stderr", "failure", "timeout", "cancelable", "large_output", "environment_probe", "stdin_probe", "secret_output_probe", "child_tree", "child_tree_resistant", "fs_read_allowed", "fs_read_external", "fs_write_allowed", "fs_write_external"}

def _deny(code: str) -> Decision:
    return Decision(False, secrets.token_urlsafe(16), SANDBOX_POLICY_VERSION, code, "Run rejected by Sandbox Guard.")

def authorize(spec: ExecutionSpec) -> Decision:
    if not isinstance(spec, ExecutionSpec): return _deny("invalid_spec")
    if spec.purpose not in _PURPOSES or spec.executable_id != "synthetic_python_module": return _deny("not_allowed")
    if spec.network_policy != "deny" or spec.environment_profile != "synthetic_minimal": return _deny("policy_not_allowed")
    if spec.filesystem_policy != "read_only_workspace_metadata" or spec.resource_profile != "small": return _deny("profile_not_allowed")
    if spec.cwd != "." or not (0 < spec.timeout_seconds <= 30) or spec.args: return _deny("arguments_not_allowed")
    argv = (sys.executable, "-m", "app.core.sandbox_tasks", spec.purpose)
    return Decision(True, secrets.token_urlsafe(16), SANDBOX_POLICY_VERSION, "allowed", "Controlled run authorized.",
        ExecutionSpec(spec.purpose, spec.executable_id, argv, ".", spec.timeout_seconds, spec.environment_profile, "deny", spec.filesystem_policy, spec.resource_profile, "sandbox_guard"))

def environment() -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(_ROOT)}


def is_sensitive_workspace_path(path: Path | str) -> bool:
    """Return whether a relative workspace path must be hidden from test jobs."""
    parts = Path(path).parts
    if not parts:
        return False
    lowered = tuple(part.casefold() for part in parts)
    return any(
        part in _SENSITIVE_DIRECTORY_NAMES
        or part == ".env"
        or part.startswith(".env.")
        or part in _SENSITIVE_FILE_NAMES
        or part.endswith(_SENSITIVE_FILE_SUFFIXES)
        for part in lowered
    )


def _canonical_python_target(target: object) -> tuple[Path, Path] | None:
    if not isinstance(target, str) or not target or len(target) > 4096:
        return None
    if target != target.strip() or "\\" in target:
        return None
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in target):
        return None
    path = Path(target)
    if (
        path.is_absolute()
        or path.as_posix() != target
        or target.startswith("-")
        or ".." in path.parts
        or path.suffix != ".py"
        or is_sensitive_workspace_path(path)
    ):
        return None
    try:
        root = Path(settings.WORKSPACE_ROOT).resolve(strict=True)
        resolved = (root / path).resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if not resolved.is_file() or resolved.suffix != ".py":
        return None
    if is_sensitive_workspace_path(relative):
        return None
    return path, resolved


def _canonical_node_target(target: object) -> tuple[Path, Path] | None:
    if not isinstance(target, str) or not target or len(target) > 4096:
        return None
    if target != target.strip() or "\\" in target:
        return None
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in target):
        return None
    path = Path(target)
    if (
        path.is_absolute()
        or path.as_posix() != target
        or target.startswith("-")
        or ".." in path.parts
        or path.suffix != ".js"
        or is_sensitive_workspace_path(path)
    ):
        return None
    try:
        root = Path(settings.WORKSPACE_ROOT).resolve(strict=True)
        resolved = (root / path).resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    if not resolved.is_file() or resolved.suffix != ".js":
        return None
    if is_sensitive_workspace_path(relative):
        return None
    return path, resolved


def trusted_node_executable() -> Path | None:
    """Return only a system Node binary covered by the Bubblewrap mounts."""
    trusted_resolved: set[Path] = set()
    for candidate in _TRUSTED_NODE_PATHS:
        try:
            trusted_resolved.add(candidate.resolve(strict=True))
        except OSError:
            continue
    for candidate in _TRUSTED_NODE_PATHS:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        try:
            status = resolved.stat()
        except OSError:
            continue
        if (
            resolved in trusted_resolved
            and resolved.is_file()
            and status.st_uid == 0
            and status.st_mode & 0o022 == 0
            and os.access(resolved, os.X_OK)
        ):
            return resolved
    return None


_UNITTEST_SELECTOR = re.compile(r"^[A-Za-z_]\w{0,127}(?:\.test_[A-Za-z0-9_]{1,120})?$")


def authorize_unittest(target: str, timeout_seconds: float, selector: str = "") -> Decision:
    if _canonical_python_target(target) is None:
        return _deny("invalid_test_target")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not (0 < timeout_seconds <= 60)
    ):
        return _deny("invalid_timeout")
    if not isinstance(selector, str) or (selector and not _UNITTEST_SELECTOR.fullmatch(selector)):
        return _deny("invalid_test_selector")
    argv = ("/usr/bin/python3", "-m", "unittest", target)
    if selector:
        argv = ("/usr/bin/python3", "-m", "unittest", "-k", selector, target)
    spec = ExecutionSpec("python_unittest", "python_unittest", argv, ".", timeout_seconds)
    return Decision(True, secrets.token_urlsafe(16), SANDBOX_POLICY_VERSION, "allowed", "Internal test authorized.", spec)


def authorize_python_file(target: str, timeout_seconds: float) -> Decision:
    """Authorize one existing workspace Python file with no user arguments."""
    if _canonical_python_target(target) is None:
        return _deny("invalid_python_target")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not (0 < timeout_seconds <= 60)
    ):
        return _deny("invalid_timeout")
    spec = ExecutionSpec(
        "python_file",
        "python_file",
        ("/usr/bin/python3", target),
        ".",
        timeout_seconds,
    )
    return Decision(
        True,
        secrets.token_urlsafe(16),
        SANDBOX_POLICY_VERSION,
        "allowed",
        "Python file authorized.",
        spec,
    )


def authorize_node_script(target: str, timeout_seconds: float) -> Decision:
    """Authorize exactly `node -- <validated-relative-js-path>`."""
    if _canonical_node_target(target) is None:
        return _deny("invalid_node_target")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not (0 < timeout_seconds <= 60)
    ):
        return _deny("invalid_timeout")
    executable = trusted_node_executable()
    if executable is None:
        return _deny("node_unavailable")
    spec = ExecutionSpec(
        "node_script",
        "node_script",
        (str(executable), "--", target),
        ".",
        timeout_seconds,
    )
    return Decision(
        True,
        secrets.token_urlsafe(16),
        SANDBOX_POLICY_VERSION,
        "allowed",
        "JavaScript file authorized.",
        spec,
    )
def contains_unsafe_argument(value: str) -> bool:
    return bool(_BAD.search(value)) or len(value) > 256 or value.startswith("/") or ".." in Path(value).parts
