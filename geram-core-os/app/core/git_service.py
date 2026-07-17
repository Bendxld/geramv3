"""Closed, local-only Git operations for repositories inside a workspace."""
from __future__ import annotations

import configparser
import hashlib
import os
import re
import signal
import stat
import subprocess
import threading
import time
import secrets
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from app.core.workspace import WorkspaceError, WorkspaceService, _public_error

GIT_TIMEOUT_SECONDS = 10.0
GIT_OUTPUT_LIMIT = 1024 * 1024
PREVIEW_TTL_SECONDS = 300
MAX_PATHS = 100
MAX_COMMIT_MESSAGE = 200
_BRANCH = re.compile(r"^(?![.-])(?!.*(?:\.\.|//|@\{|\\|\s|[~^:?*\[]))[A-Za-z0-9._/-]{1,120}(?<![./-])$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_DANGEROUS_CONFIG_SECTIONS = ("filter ", "diff ", "merge ", "credential ", "include", "includeif")
_DANGEROUS_CONFIG_KEYS = {
    "core.hookspath", "core.fsmonitor", "core.sshcommand", "core.editor",
    "core.attributesfile", "core.excludesfile", "core.worktree", "sequence.editor",
}


class GitService:
    """Git facade whose public methods map to fixed argument templates only."""

    def __init__(self, workspace: WorkspaceService, git_path: Path | None = None):
        self.workspace = workspace
        self.git_path = git_path
        self._lock = threading.RLock()
        self._previews: dict[str, dict[str, Any]] = {}

    def _trusted_git(self) -> Path:
        candidates = (Path("/usr/bin/git"), Path("/bin/git"))
        candidate = self.git_path or next((item for item in candidates if item.is_file()), None)
        if candidate is None:
            raise _public_error("git_unavailable", "The trusted Git executable is unavailable", 503)
        try:
            resolved = candidate.resolve(strict=True)
            info = resolved.stat()
        except OSError:
            raise _public_error("git_unavailable", "The trusted Git executable is unavailable", 503) from None
        trusted = {item.resolve(strict=False) for item in candidates}
        if resolved not in trusted or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise _public_error("git_unavailable", "The trusted Git executable is unavailable", 503)
        return resolved

    def _project_path(self, raw_path: str) -> Path:
        if raw_path == "":
            return self.workspace.root
        resolved = self.workspace.resolve_path(raw_path)
        candidate = self.workspace.root.joinpath(*resolved.parts)
        if candidate.exists() and not candidate.is_dir():
            candidate = candidate.parent
        return candidate

    def repository(self, project: str = "") -> tuple[Path, str]:
        current = self._project_path(project)
        while True:
            metadata = current / ".git"
            try:
                metadata_info = os.lstat(metadata)
                if stat.S_ISLNK(metadata_info.st_mode) or not stat.S_ISDIR(metadata_info.st_mode):
                    raise _public_error("unsafe_repository", "The repository metadata is unsafe", 403)
                if stat.S_ISDIR(metadata_info.st_mode):
                    root = current.resolve(strict=True)
                    root.relative_to(self.workspace.root)
                    if not stat.S_ISDIR(os.lstat(metadata).st_mode):
                        raise _public_error("unsafe_repository", "The repository metadata is unsafe", 403)
                    relative = root.relative_to(self.workspace.root).as_posix()
                    self._validate_repository_policy(root)
                    return root, "" if relative == "." else relative
            except FileNotFoundError:
                pass
            except WorkspaceError:
                raise
            except (OSError, ValueError):
                raise _public_error("unsafe_repository", "The repository is outside the workspace", 403) from None
            if current == self.workspace.root:
                break
            if self.workspace.root not in current.parents:
                break
            current = current.parent
        raise _public_error("git_repository_not_found", "No Git repository was found for this project", 404)

    def _validate_repository_policy(self, root: Path) -> None:
        metadata = root / ".git"
        for relative, expected_directory in (("config", False), ("objects", True), ("refs", True)):
            candidate = metadata / relative
            try:
                info = os.lstat(candidate)
            except FileNotFoundError:
                continue
            expected = stat.S_ISDIR(info.st_mode) if expected_directory else stat.S_ISREG(info.st_mode)
            if stat.S_ISLNK(info.st_mode) or not expected:
                raise _public_error("unsafe_repository", "The repository metadata is unsafe", 403)
        for unsupported in (metadata / "commondir", metadata / "objects" / "info" / "alternates"):
            if unsupported.exists() or unsupported.is_symlink():
                raise _public_error("unsafe_repository", "External Git object stores are not allowed", 403)
        config_path = root / ".git" / "config"
        try:
            data = config_path.read_bytes()
        except OSError:
            raise _public_error("unsafe_repository", "The repository configuration is unavailable", 403) from None
        if len(data) > 256 * 1024 or b"\0" in data:
            raise _public_error("unsafe_repository", "The repository configuration is unsafe", 403)
        try:
            parser = configparser.RawConfigParser(interpolation=None, strict=False)
            parser.read_string(data.decode("utf-8"))
        except (UnicodeDecodeError, configparser.Error):
            raise _public_error("unsafe_repository", "The repository configuration is unsafe", 403) from None
        for section in parser.sections():
            lowered = section.casefold()
            if lowered.startswith(_DANGEROUS_CONFIG_SECTIONS):
                raise _public_error("unsafe_repository_config", "Executable Git configuration is not allowed", 403)
            for key, _value in parser.items(section):
                if f"{lowered}.{key.casefold()}" in _DANGEROUS_CONFIG_KEYS:
                    raise _public_error("unsafe_repository_config", "Executable Git configuration is not allowed", 403)
        attributes = [root / ".gitattributes", root / ".git" / "info" / "attributes"]
        for attribute_file in attributes:
            if not attribute_file.exists():
                continue
            try:
                content = attribute_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                raise _public_error("unsafe_repository_attributes", "Git attributes are unsafe", 403) from None
            if len(content) > 256 * 1024 or re.search(r"(?:^|\s)(?:filter|diff|merge)(?:=|\s)", content, re.MULTILINE | re.IGNORECASE):
                raise _public_error("unsafe_repository_attributes", "Executable Git attributes are not allowed", 403)

    @staticmethod
    def _environment(read_only: bool) -> dict[str, str]:
        environment = {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "GIT_PAGER": "cat",
            "GIT_EDITOR": "/bin/false", "GIT_SEQUENCE_EDITOR": "/bin/false",
        }
        if read_only:
            environment["GIT_OPTIONAL_LOCKS"] = "0"
        return environment

    def _run(self, root: Path, arguments: Sequence[str], *, read_only: bool = True, timeout: float = GIT_TIMEOUT_SECONDS) -> bytes:
        prefix = [
            str(self._trusted_git()), "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
            "-c", "core.untrackedCache=false", "-c", "commit.gpgSign=false",
            "-c", "gc.auto=0", "-c", "maintenance.auto=false",
        ]
        process = None
        try:
            metadata_before = os.lstat(root / ".git")
            if not stat.S_ISDIR(metadata_before.st_mode):
                raise OSError
            process = subprocess.Popen(
                prefix + list(arguments), cwd=root, env=self._environment(read_only),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, shell=False,
            )
            stdout, stderr = process.communicate(timeout=timeout)
            metadata_after = os.lstat(root / ".git")
            if (metadata_before.st_dev, metadata_before.st_ino) != (metadata_after.st_dev, metadata_after.st_ino):
                raise _public_error("unsafe_repository", "The repository metadata changed during the operation", 409)
        except WorkspaceError:
            raise
        except subprocess.TimeoutExpired:
            if process is not None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.communicate()
            raise _public_error("git_timeout", "The Git operation timed out", 504) from None
        except OSError:
            raise _public_error("git_unavailable", "Git could not be started", 503) from None
        if len(stdout) > GIT_OUTPUT_LIMIT or len(stderr) > GIT_OUTPUT_LIMIT:
            raise _public_error("git_output_limit", "The Git output exceeded the safety limit", 413)
        if process.returncode != 0:
            code = "git_operation_failed"
            if process.returncode == 1 and arguments and arguments[0] == "diff":
                code = "git_diff_failed"
            raise _public_error(code, "The Git operation could not be completed", 409)
        return stdout

    def _verify_repository(self, root: Path) -> None:
        output = self._run(root, ["rev-parse", "--show-toplevel"]).decode("utf-8", "strict").strip()
        try:
            if Path(output).resolve(strict=True) != root:
                raise ValueError
        except (OSError, ValueError):
            raise _public_error("unsafe_repository", "Git resolved outside the authorized repository", 403) from None

    def _validate_paths(self, root: Path, repo_relative: str, paths: Sequence[str], *, existing: bool = False) -> list[str]:
        if not isinstance(paths, (list, tuple)) or not paths or len(paths) > MAX_PATHS:
            raise _public_error("invalid_git_paths", "A bounded file selection is required", 422)
        validated = []
        for raw in paths:
            if not isinstance(raw, str) or not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
                raise _public_error("invalid_git_path", "A valid relative Git path is required", 422)
            workspace_path = PurePosixPath(repo_relative, raw).as_posix() if repo_relative else raw
            resolved = self.workspace.resolve_path(workspace_path)
            candidate = self.workspace.root.joinpath(*resolved.parts)
            try:
                candidate.resolve(strict=False).relative_to(root)
            except (OSError, ValueError):
                raise _public_error("git_path_outside_repository", "The Git path is outside the repository", 403) from None
            if candidate.is_symlink():
                raise _public_error("symlink_not_allowed", "Symbolic links cannot be changed by Source Control", 403)
            if candidate.exists():
                info = candidate.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise _public_error("invalid_git_path", "Only files can be selected", 422)
                self.workspace._reject_hardlink(info)
                self.workspace.read_file(workspace_path)
            elif existing:
                raise _public_error("not_found", "The selected file does not exist", 404)
            validated.append(PurePosixPath(*resolved.parts[len(PurePosixPath(repo_relative).parts):]).as_posix() if repo_relative else resolved.relative)
        return list(dict.fromkeys(validated))

    @staticmethod
    def _parse_status(data: bytes) -> dict[str, Any]:
        records = data.split(b"\0")
        entries: list[dict[str, Any]] = []
        branch = ""
        index = 0
        while index < len(records):
            raw = records[index]
            index += 1
            if not raw:
                continue
            line = raw.decode("utf-8", "strict")
            if line.startswith("# branch.head "):
                branch = line[14:]
                continue
            if line.startswith("? "):
                entries.append({"path": line[2:], "original_path": "", "index": ".", "worktree": "?", "kind": "untracked", "staged": False})
                continue
            if line.startswith("! "):
                continue
            if line.startswith("1 "):
                parts = line.split(" ", 8)
                xy, path = parts[1], parts[8]
                entries.append(GitService._status_entry(path, "", xy))
                continue
            if line.startswith("2 "):
                parts = line.split(" ", 9)
                xy, path = parts[1], parts[9]
                original = records[index].decode("utf-8", "strict") if index < len(records) else ""
                index += 1
                entries.append(GitService._status_entry(path, original, xy))
                continue
            if line.startswith("u "):
                parts = line.split(" ", 10)
                entry = GitService._status_entry(parts[10], "", parts[1])
                entry["kind"] = "conflict"
                entries.append(entry)
        return {"branch": branch, "entries": entries, "clean": not entries, "conflicts": sum(item["kind"] == "conflict" for item in entries)}

    @staticmethod
    def _status_entry(path: str, original: str, xy: str) -> dict[str, Any]:
        staged = xy[0] != "."
        if "U" in xy or xy in {"AA", "DD"}: kind = "conflict"
        elif "R" in xy: kind = "renamed"
        elif "D" in xy: kind = "deleted"
        else: kind = "modified"
        return {"path": path, "original_path": original, "index": xy[0], "worktree": xy[1], "kind": kind, "staged": staged}

    def status(self, project: str = "") -> dict[str, Any]:
        root, relative = self.repository(project)
        self._verify_repository(root)
        try:
            result = self._parse_status(self._run(root, ["status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"]))
        except UnicodeDecodeError:
            raise _public_error("unsafe_repository_path", "The repository contains unsupported file names", 403) from None
        raw_entries = result["entries"]
        visible = []
        for entry in raw_entries:
            try:
                self._validate_paths(root, relative, [entry["path"]])
                if entry["original_path"]:
                    self._validate_paths(root, relative, [entry["original_path"]])
            except WorkspaceError:
                continue
            visible.append(entry)
        result["entries"] = visible
        result["restricted"] = len(raw_entries) - len(visible)
        result["restricted_staged"] = sum(item["staged"] for item in raw_entries if item not in visible)
        result["clean"] = not raw_entries
        result["conflicts"] = sum(item["kind"] == "conflict" for item in visible)
        result["repository"] = relative
        return result

    def diff(self, project: str, path: str, staged: bool = False) -> dict[str, Any]:
        root, relative = self.repository(project)
        validated = self._validate_paths(root, relative, [path])[0]
        arguments = ["diff", "--no-ext-diff", "--no-textconv", "--unified=3"]
        if staged: arguments.append("--cached")
        arguments.extend(["--", validated])
        output = self._run(root, arguments).decode("utf-8", "replace")
        return {"path": validated, "staged": staged, "diff": output}

    def stage(self, project: str, paths: Sequence[str]) -> dict[str, Any]:
        with self._lock:
            root, relative = self.repository(project)
            validated = self._validate_paths(root, relative, paths)
            current = self.status(project)
            entries = {item["path"]: item for item in current["entries"]}
            if all(path in entries and entries[path]["staged"] for path in validated):
                return current
            self._run(root, ["add", "--", *validated], read_only=False)
            return self.status(project)

    def unstage(self, project: str, paths: Sequence[str]) -> dict[str, Any]:
        with self._lock:
            root, relative = self.repository(project)
            validated = self._validate_paths(root, relative, paths)
            validated = self._expand_renames(project, validated)
            self._run(root, ["restore", "--staged", "--", *validated], read_only=False)
            return self.status(project)

    def _expand_renames(self, project: str, paths: list[str]) -> list[str]:
        selected = list(paths)
        for entry in self.status(project)["entries"]:
            if entry["kind"] == "renamed" and entry["path"] in paths and entry["original_path"]:
                selected.append(entry["original_path"])
        return list(dict.fromkeys(selected))

    @staticmethod
    def validate_message(message: object) -> str:
        if not isinstance(message, str) or message != message.strip() or not 1 <= len(message) <= MAX_COMMIT_MESSAGE:
            raise _public_error("invalid_commit_message", "A valid commit message is required", 422)
        if any(ord(character) < 32 or ord(character) == 127 for character in message):
            raise _public_error("invalid_commit_message", "The commit message contains invalid characters", 422)
        return message

    def preview_commit(self, project: str, message: object) -> dict[str, Any]:
        clean_message = self.validate_message(message)
        status = self.status(project)
        if status["restricted_staged"]:
            raise _public_error("restricted_staged_changes", "Protected staged changes must be removed outside GERAM", 409)
        staged = [item for item in status["entries"] if item["staged"]]
        if not staged:
            raise _public_error("empty_commit", "There are no staged changes to commit", 409)
        root, _relative = self.repository(project)
        token = self._store_preview(
            "commit", project=project, message=clean_message,
            paths=[item["path"] for item in staged], digest=self._staged_digest(root),
        )
        return {"token": token, "message": clean_message, "files": staged}

    def apply_commit(self, token: str) -> dict[str, str]:
        preview = self._consume_preview(token, "commit")
        with self._lock:
            current = self.status(preview["project"])
            root, _relative = self.repository(preview["project"])
            if (
                current["restricted_staged"]
                or [item["path"] for item in current["entries"] if item["staged"]] != preview["paths"]
                or self._staged_digest(root) != preview["digest"]
            ):
                raise _public_error("git_operation_conflict", "The staged changes changed before commit", 409)
            self._run(root, ["commit", "--no-verify", "--no-gpg-sign", "-m", preview["message"]], read_only=False)
            short_hash = self._run(root, ["rev-parse", "--short=12", "HEAD"]).decode().strip()
            return {"hash": short_hash, "message": preview["message"]}

    def _staged_digest(self, root: Path) -> str:
        data = self._run(root, ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--full-index", "--binary"])
        return hashlib.sha256(data).hexdigest()

    def branches(self, project: str) -> dict[str, Any]:
        root, relative = self.repository(project)
        output = self._run(root, ["branch", "--list", "--format=%(refname:short)%00%(HEAD)"]).split(b"\n")
        branches = []
        for line in output:
            if not line: continue
            name, current = line.decode("utf-8", "strict").split("\0", 1)
            branches.append({"name": name, "current": current == "*"})
        return {"repository": relative, "branches": branches}

    @staticmethod
    def validate_branch(name: object) -> str:
        if not isinstance(name, str) or not _BRANCH.fullmatch(name) or name.endswith(".lock"):
            raise _public_error("invalid_branch", "The branch name is invalid", 422)
        return name

    def switch(self, project: str, branch: object, *, create: bool = False) -> dict[str, Any]:
        name = self.validate_branch(branch)
        with self._lock:
            status = self.status(project)
            if not status["clean"]:
                raise _public_error("dirty_worktree", "Branch switching requires a clean worktree", 409)
            root, _relative = self.repository(project)
            arguments = ["switch", "-c", name] if create else ["switch", name]
            self._run(root, arguments, read_only=False)
            return self.status(project)

    def preview_discard(self, project: str, path: str) -> dict[str, Any]:
        root, relative = self.repository(project)
        validated = self._validate_paths(root, relative, [path])[0]
        output = self.diff(project, validated, False)["diff"]
        if not output:
            raise _public_error("nothing_to_discard", "There are no working tree changes to discard", 409)
        token = self._store_preview("discard", project=project, path=validated, diff=output)
        return {"token": token, "path": validated, "diff": output}

    def apply_discard(self, token: str) -> dict[str, Any]:
        preview = self._consume_preview(token, "discard")
        with self._lock:
            if self.diff(preview["project"], preview["path"], False)["diff"] != preview["diff"]:
                raise _public_error("git_operation_conflict", "The file changed before discard", 409)
            root, relative = self.repository(preview["project"])
            path = self._validate_paths(root, relative, [preview["path"]])[0]
            self._run(root, ["restore", "--worktree", "--", path], read_only=False)
            return {"path": path, "status": self.status(preview["project"])}

    def _store_preview(self, action: str, **values: Any) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._expire_locked()
            self._previews[token] = {"action": action, "created": time.monotonic(), **values}
        return token

    def _consume_preview(self, token: str, action: str) -> dict[str, Any]:
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise _public_error("invalid_git_token", "The Source Control token is invalid", 422)
        with self._lock:
            self._expire_locked()
            preview = self._previews.pop(token, None)
        if preview is None or preview["action"] != action:
            raise _public_error("git_preview_not_found", "The Source Control preview was not found", 404)
        return preview

    def _expire_locked(self) -> None:
        now = time.monotonic()
        for token, preview in tuple(self._previews.items()):
            if now - preview["created"] > PREVIEW_TTL_SECONDS:
                self._previews.pop(token, None)
