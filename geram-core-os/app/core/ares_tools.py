"""Read-only, workspace-scoped tools A.R.E.S. may call while drafting a proposal.

Every tool here is strictly read-only and bounded. There is deliberately no
write, delete, move, rename, shell, or network tool: the only mutation A.R.E.S.
can ever cause still flows through the proposal -> approve -> apply gate.
WorkspaceService and the search service remain the sole authorities for path
canonicalization, exclusions, UTF-8 validation, and size limits — this module
only forwards to them and caps the volume returned to the model.
"""

from __future__ import annotations

import threading

from app.api.workspace import workspace_service
from app.api.workspace_navigation import search_service
from app.core.workspace import WorkspaceError
from app.core.workspace_search import SearchError, SearchOptions

# Bounds keep a single tool result small enough to stay well inside the model
# context and prevent a tool loop from exfiltrating the whole workspace at once.
MAX_TOOL_RESULT_CHARS = 8000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 50


class AresToolError(Exception):
    """A bounded, safe-to-surface tool failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def tool_definitions() -> list[dict]:
    """OpenAI Responses function-tool schemas for the read-only toolset."""
    return [
        {
            "type": "function",
            "name": "read_file",
            "description": (
                "Read a UTF-8 text file from the workspace by its canonical "
                "relative path. Returns the current content (possibly "
                "truncated) and its version."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path"}
                },
            },
        },
        {
            "type": "function",
            "name": "list_files",
            "description": (
                "List workspace file paths. Pass an empty prefix for all files, "
                "or a path prefix to filter (e.g. 'app/api/')."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["prefix"],
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Path prefix filter; empty string returns all files",
                    }
                },
            },
        },
        {
            "type": "function",
            "name": "search_text",
            "description": (
                "Case-insensitive plain-text search across the workspace. "
                "Returns matching file paths, line numbers, and line previews."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"}
                },
            },
        },
    ]


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text, False
    return text[:MAX_TOOL_RESULT_CHARS], True


def _read_file(path: object) -> dict:
    if not isinstance(path, str) or not path.strip():
        raise AresToolError("invalid_path", "read_file requires a non-empty path")
    try:
        result = workspace_service.read_file(path)
    except WorkspaceError as error:
        raise AresToolError(error.code, str(error)) from None
    content, truncated = _truncate(str(result.get("content", "")))
    return {
        "path": result.get("path", path),
        "content": content,
        "truncated": truncated,
        "version": result.get("version"),
    }


def _list_files(prefix: object) -> dict:
    normalized = str(prefix or "").strip().lstrip("/")
    try:
        listing = search_service.files()
    except WorkspaceError as error:
        raise AresToolError(error.code, str(error)) from None
    paths = [p for p in listing.get("files", []) if isinstance(p, str)]
    if normalized:
        paths = [p for p in paths if p.startswith(normalized)]
    truncated = bool(listing.get("truncated")) or len(paths) > MAX_LIST_ENTRIES
    return {"prefix": normalized, "paths": paths[:MAX_LIST_ENTRIES], "truncated": truncated}


def _search_text(query: object) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise AresToolError("invalid_query", "search_text requires a non-empty query")
    options = SearchOptions(
        query=query,
        regex=False,
        case_sensitive=False,
        whole_word=False,
        include=(),
        exclude=(),
        limit=MAX_SEARCH_RESULTS,
    )
    try:
        found = search_service.search(options, threading.Event())
    except (SearchError, WorkspaceError) as error:
        raise AresToolError(error.code, str(error)) from None
    results = found.get("results", [])[:MAX_SEARCH_RESULTS]
    return {"results": results, "limited": bool(found.get("limited"))}


_DISPATCH = {
    "read_file": lambda args: _read_file(args.get("path", "")),
    "list_files": lambda args: _list_files(args.get("prefix", "")),
    "search_text": lambda args: _search_text(args.get("query", "")),
}


def execute_tool(name: str, arguments: dict) -> dict:
    """Run one read-only tool by name. Raises AresToolError on any bad input."""
    if not isinstance(arguments, dict):
        raise AresToolError("invalid_arguments", "tool arguments must be an object")
    handler = _DISPATCH.get(name)
    if handler is None:
        raise AresToolError("unknown_tool", f"unknown tool: {name}")
    return handler(arguments)
