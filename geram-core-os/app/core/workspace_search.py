"""Bounded local workspace search and approval-gated multi-file replacement."""
from __future__ import annotations

import fnmatch
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.workspace import WorkspaceError, WorkspaceService

MAX_QUERY_LENGTH = 256
MAX_FILTERS = 16
MAX_FILTER_LENGTH = 128
MAX_RESULTS = 500
MAX_SEARCH_SECONDS = 10.0
MAX_REPLACE_FILES = 100
MAX_REPLACE_BYTES = 8 * 1024 * 1024
PREVIEW_TTL_SECONDS = 300


class SearchError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class SearchOptions:
    query: str
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    limit: int = 200


def _validate_filters(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or len(values) > MAX_FILTERS:
        raise SearchError("invalid_search_filter")
    result = []
    for value in values:
        if not isinstance(value, str) or not value or len(value) > MAX_FILTER_LENGTH or "\\" in value or ".." in value.split("/"):
            raise SearchError("invalid_search_filter")
        result.append(value)
    return tuple(result)


def _safe_regex(pattern: str) -> None:
    """Accept useful linear-looking patterns and reject high-risk constructs."""
    if any(token in pattern for token in ("(", ")", "{", "}", "(?", "\\1", "\\2", "\\g")):
        raise SearchError("unsafe_regular_expression")
    if re.search(r"(?:\*|\+|\?){2,}", pattern):
        raise SearchError("unsafe_regular_expression")


def compile_pattern(options: SearchOptions) -> re.Pattern[str]:
    query = options.query
    if not isinstance(query, str) or not query or len(query) > MAX_QUERY_LENGTH or "\x00" in query:
        raise SearchError("invalid_search_query")
    source = query
    if options.regex:
        _safe_regex(source)
    else:
        source = re.escape(source)
    if options.whole_word:
        source = r"\b(?:" + source + r")\b"
    try:
        return re.compile(source, 0 if options.case_sensitive else re.IGNORECASE)
    except re.error:
        raise SearchError("invalid_regular_expression") from None


def fuzzy_score(query: str, path: str) -> int | None:
    """Deterministic subsequence score; smaller is a better match."""
    needle = query.casefold().strip()
    haystack = path.casefold()
    if not needle:
        return 0
    positions: list[int] = []
    start = 0
    for character in needle:
        index = haystack.find(character, start)
        if index < 0:
            return None
        positions.append(index)
        start = index + 1
    span = positions[-1] - positions[0] + 1
    basename = path.rsplit("/", 1)[-1].casefold()
    bonus = -100 if basename.startswith(needle) else (-50 if needle in basename else 0)
    return span * 4 + positions[0] + len(path) + bonus


class WorkspaceSearchService:
    def __init__(self, workspace: WorkspaceService):
        self.workspace = workspace
        self._previews: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def files(self) -> dict[str, Any]:
        tree = self.workspace.tree()
        files = []
        for entry in tree["entries"]:
            if entry.get("type") != "file" or not entry.get("editable"):
                continue
            try:
                self.workspace.read_file(entry["path"])
            except WorkspaceError:
                continue
            files.append(entry["path"])
        return {"files": files, "truncated": bool(tree.get("truncated") or tree.get("depth_limited"))}

    @staticmethod
    def _selected(path: str, include: tuple[str, ...], exclude: tuple[str, ...]) -> bool:
        if include and not any(fnmatch.fnmatchcase(path, pattern) for pattern in include):
            return False
        return not any(fnmatch.fnmatchcase(path, pattern) for pattern in exclude)

    def search(self, options: SearchOptions, cancel: threading.Event | None = None) -> dict[str, Any]:
        include = _validate_filters(options.include)
        exclude = _validate_filters(options.exclude)
        if isinstance(options.limit, bool) or not 1 <= options.limit <= MAX_RESULTS:
            raise SearchError("invalid_result_limit")
        pattern = compile_pattern(options)
        results: list[dict[str, Any]] = []
        scanned = 0
        deadline = time.monotonic() + MAX_SEARCH_SECONDS
        for path in self.files()["files"]:
            if cancel and cancel.is_set():
                raise SearchError("search_cancelled", 409)
            if time.monotonic() > deadline:
                raise SearchError("search_timeout", 408)
            if not self._selected(path, include, exclude):
                continue
            try:
                document = self.workspace.read_file(path)
            except WorkspaceError:
                continue
            scanned += 1
            for line_number, line in enumerate(document["content"].splitlines(), 1):
                if cancel and cancel.is_set():
                    raise SearchError("search_cancelled", 409)
                if time.monotonic() > deadline:
                    raise SearchError("search_timeout", 408)
                for match in pattern.finditer(line):
                    results.append({
                        "path": path,
                        "line": line_number,
                        "column": match.start() + 1,
                        "end_column": match.end() + 1,
                        "preview": line[:240],
                    })
                    if len(results) >= options.limit:
                        return {"results": results, "limited": True, "scanned_files": scanned}
                    if match.start() == match.end():
                        break
        return {"results": results, "limited": False, "scanned_files": scanned}

    def preview_replace(self, options: SearchOptions, replacement: str) -> dict[str, Any]:
        if not isinstance(replacement, str) or len(replacement.encode("utf-8")) > 256 * 1024:
            raise SearchError("invalid_replacement")
        include = _validate_filters(options.include)
        exclude = _validate_filters(options.exclude)
        pattern = compile_pattern(options)
        edits = []
        total_bytes = 0
        total_matches = 0
        for path in self.files()["files"]:
            if not self._selected(path, include, exclude):
                continue
            try:
                document = self.workspace.read_file(path)
            except WorkspaceError:
                continue
            content, count = pattern.subn(lambda _match: replacement, document["content"])
            if not count:
                continue
            total_bytes += len(content.encode("utf-8"))
            if len(edits) >= MAX_REPLACE_FILES or total_bytes > MAX_REPLACE_BYTES:
                raise SearchError("replacement_too_large", 413)
            edits.append({
                "path": path, "content": content, "base_version": document["version"], "matches": count,
            })
            total_matches += count
        if not edits:
            raise SearchError("replacement_empty", 409)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._expire_locked()
            self._previews[token] = {"created": time.monotonic(), "edits": edits}
        return {
            "token": token,
            "files": [{"path": edit["path"], "matches": edit["matches"]} for edit in edits],
            "total_matches": total_matches,
        }

    def apply_replace(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", token):
            raise SearchError("invalid_replacement_token")
        with self._lock:
            self._expire_locked()
            preview = self._previews.pop(token, None)
        if preview is None:
            raise SearchError("replacement_not_found", 404)
        edits = [{key: edit[key] for key in ("path", "content", "base_version")} for edit in preview["edits"]]
        results = self.workspace.save_files_atomically(edits)
        return {"applied": results}

    def _expire_locked(self) -> None:
        now = time.monotonic()
        for token, preview in tuple(self._previews.items()):
            if now - preview["created"] > PREVIEW_TTL_SECONDS:
                self._previews.pop(token, None)
