"""Bounded static unittest discovery; modules are never imported or executed."""
from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import Any

from app.core.workspace import WorkspaceError, WorkspaceService, _public_error

MAX_DISCOVERY_FILES = 200
MAX_DISCOVERED_TESTS = 1000
MAX_AST_NODES = 50_000


class UnittestDiscovery:
    def __init__(self, workspace: WorkspaceService):
        self.workspace = workspace

    @staticmethod
    def _base_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = UnittestDiscovery._base_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""

    def discover(self) -> dict[str, Any]:
        tree = self.workspace.tree()
        paths = [
            entry["path"] for entry in tree["entries"]
            if entry["type"] == "file" and entry["path"].endswith(".py") and entry.get("editable") is not False
        ][:MAX_DISCOVERY_FILES]
        files = []
        total = 0
        for path in paths:
            try:
                document = self.workspace.read_file(path)
                parsed = ast.parse(document["content"], filename=path, mode="exec")
            except (WorkspaceError, SyntaxError, ValueError, RecursionError):
                continue
            if sum(1 for _node in ast.walk(parsed)) > MAX_AST_NODES:
                continue
            aliases = {"unittest.TestCase", "TestCase"}
            for node in parsed.body:
                if isinstance(node, ast.ImportFrom) and node.module == "unittest":
                    for imported in node.names:
                        if imported.name == "TestCase": aliases.add(imported.asname or imported.name)
                elif isinstance(node, ast.Import):
                    for imported in node.names:
                        if imported.name == "unittest": aliases.add((imported.asname or "unittest") + ".TestCase")
            classes = []
            for node in parsed.body:
                if not isinstance(node, ast.ClassDef) or not any(self._base_name(base) in aliases for base in node.bases):
                    continue
                methods = []
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                        methods.append({
                            "name": child.name, "selector": f"{node.name}.{child.name}",
                            "line": child.lineno, "column": child.col_offset + 1,
                        })
                        total += 1
                        if total >= MAX_DISCOVERED_TESTS: break
                if methods:
                    classes.append({
                        "name": node.name, "selector": node.name, "line": node.lineno,
                        "column": node.col_offset + 1, "methods": methods,
                    })
                if total >= MAX_DISCOVERED_TESTS: break
            if classes:
                files.append({"path": path, "name": PurePosixPath(path).name, "classes": classes})
            if total >= MAX_DISCOVERED_TESTS: break
        return {
            "files": files, "total": total,
            "limited": len(paths) >= MAX_DISCOVERY_FILES or total >= MAX_DISCOVERED_TESTS or tree.get("truncated", False),
        }
