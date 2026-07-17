import threading
import tempfile
import time
import unittest
from pathlib import Path

from app.core.workspace import WorkspaceError, WorkspaceService
from app.core.workspace_search import (
    SearchError, SearchOptions, WorkspaceSearchService, compile_pattern, fuzzy_score,
)
from fastapi.testclient import TestClient
from app.main import app
from app.api import workspace_navigation
from app.core.security import require_localhost


class WorkspaceSearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src/main.py").write_text("def calculateTotal(value: int):\n    return value + 1\n", encoding="utf-8")
        (self.root / "src/app.js").write_text("function calculateTotal(value) {\n  return value + 1;\n}\n", encoding="utf-8")
        (self.root / "README.md").write_text("Calculate total safely.\ncalculate other\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=private\n", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules/hidden.js").write_text("calculateTotal secret\n", encoding="utf-8")
        self.workspace = WorkspaceService(self.root)
        self.search = WorkspaceSearchService(self.workspace)

    def tearDown(self):
        self.temporary.cleanup()

    def test_files_and_fuzzy_matching_exclude_sensitive_dependencies_and_binary(self):
        (self.root / "image.png").write_bytes(b"\x89PNG\x00")
        files = self.search.files()["files"]
        self.assertEqual(files, ["src/app.js", "src/main.py", "README.md"])
        self.assertLess(fuzzy_score("smp", "src/main.py"), fuzzy_score("smp", "long/src/main.py"))
        self.assertIsNone(fuzzy_score("zzz", "src/main.py"))

    def test_literal_case_sensitive_whole_word_and_filters(self):
        insensitive = self.search.search(SearchOptions("calculate", limit=20))
        self.assertEqual(len(insensitive["results"]), 4)
        sensitive = self.search.search(SearchOptions("Calculate", case_sensitive=True, limit=20))
        self.assertEqual([item["path"] for item in sensitive["results"]], ["README.md"])
        whole = self.search.search(SearchOptions("calculate", whole_word=True, limit=20))
        self.assertEqual(len(whole["results"]), 2)
        included = self.search.search(SearchOptions("calculate", include=("src/*.js",), limit=20))
        self.assertEqual({item["path"] for item in included["results"]}, {"src/app.js"})
        excluded = self.search.search(SearchOptions("calculate", exclude=("*.md", "**/*.py"), limit=20))
        self.assertEqual({item["path"] for item in excluded["results"]}, {"src/app.js"})

    def test_valid_invalid_and_unsafe_regex(self):
        result = self.search.search(SearchOptions(r"calculate[A-Z].*", regex=True, limit=20))
        self.assertEqual(len(result["results"]), 2)
        with self.assertRaisesRegex(SearchError, "invalid_regular_expression"):
            compile_pattern(SearchOptions("[", regex=True))
        for value in ("(a+)+", "a{1,5}", "a**"):
            with self.subTest(value=value), self.assertRaises(SearchError):
                compile_pattern(SearchOptions(value, regex=True))

    def test_cancellation_and_limit_are_enforced(self):
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaisesRegex(SearchError, "search_cancelled"):
            self.search.search(SearchOptions("calculate"), cancelled)
        limited = self.search.search(SearchOptions("a", limit=2))
        self.assertEqual(len(limited["results"]), 2)
        self.assertTrue(limited["limited"])

    def test_replace_requires_preview_and_explicit_apply(self):
        preview = self.search.preview_replace(SearchOptions("calculateTotal", case_sensitive=True), "sumValues")
        self.assertEqual(preview["total_matches"], 2)
        self.assertEqual({item["path"] for item in preview["files"]}, {"src/app.js", "src/main.py"})
        self.assertIn("calculateTotal", (self.root / "src/app.js").read_text())
        applied = self.search.apply_replace(preview["token"])
        self.assertEqual(len(applied["applied"]), 2)
        self.assertIn("sumValues", (self.root / "src/app.js").read_text())
        with self.assertRaisesRegex(SearchError, "replacement_not_found"):
            self.search.apply_replace(preview["token"])

    def test_replace_conflict_rejects_every_file_without_partial_write(self):
        preview = self.search.preview_replace(SearchOptions("value"), "amount")
        original_js = (self.root / "src/app.js").read_text()
        (self.root / "src/main.py").write_text("external change\n", encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "changed"):
            self.search.apply_replace(preview["token"])
        self.assertEqual((self.root / "src/app.js").read_text(), original_js)

    def test_traversal_external_symlink_and_sensitive_paths_never_search_or_replace(self):
        outside = self.root.parent / "outside-search.txt"
        outside.write_text("calculateTotal\n", encoding="utf-8")
        (self.root / "external.py").symlink_to(outside)
        try:
            paths = {item["path"] for item in self.search.search(SearchOptions("calculateTotal"))["results"]}
            self.assertNotIn("external.py", paths)
            self.assertNotIn(".env", self.search.files()["files"])
            with self.assertRaises(WorkspaceError):
                self.workspace.read_file("../outside-search.txt")
        finally:
            outside.unlink(missing_ok=True)


class WorkspaceNavigationApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "main.py").write_text("needle one\nneedle two\n", encoding="utf-8")
        self.previous = workspace_navigation.search_service
        workspace_navigation.search_service = WorkspaceSearchService(WorkspaceService(self.root))
        app.dependency_overrides[require_localhost] = lambda: None
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")
        self.headers = {"Origin": "http://127.0.0.1:8000"}

    def tearDown(self):
        workspace_navigation.search_service = self.previous
        app.dependency_overrides.pop(require_localhost, None)
        self.temporary.cleanup()

    def test_search_job_completes_and_returns_bounded_results(self):
        started = self.client.post("/api/navigation/search/jobs", json={"query": "needle", "limit": 1}, headers=self.headers)
        self.assertEqual(started.status_code, 202)
        job_id = started.json()["job_id"]
        for _ in range(100):
            response = self.client.get(f"/api/navigation/search/jobs/{job_id}")
            if response.json()["status"] != "searching":
                break
            time.sleep(0.01)
        payload = response.json()
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(len(payload["result"]["results"]), 1)
        self.assertTrue(payload["result"]["limited"])

    def test_mutations_require_local_origin_and_cancel_is_explicit(self):
        denied = self.client.post("/api/navigation/search/jobs", json={"query": "needle"}, headers={"Origin": "https://example.invalid"})
        self.assertEqual(denied.status_code, 403)
        started = self.client.post("/api/navigation/search/jobs", json={"query": "needle"}, headers=self.headers).json()
        cancelled = self.client.delete(f"/api/navigation/search/jobs/{started['job_id']}", headers=self.headers)
        self.assertEqual(cancelled.json(), {"status": "cancelled"})
        self.assertEqual(self.client.get(f"/api/navigation/search/jobs/{started['job_id']}").json()["status"], "cancelled")

    def test_schema_rejects_extra_fields_invalid_regex_and_bad_filters(self):
        extra = self.client.post("/api/navigation/search", json={"query": "x", "command": "rm"}, headers=self.headers)
        self.assertEqual(extra.status_code, 422)
        regex = self.client.post("/api/navigation/search", json={"query": "[", "regex": True}, headers=self.headers)
        self.assertEqual(regex.status_code, 422)
        bad_filter = self.client.post("/api/navigation/search", json={"query": "x", "include": ["../*"]}, headers=self.headers)
        self.assertEqual(bad_filter.status_code, 422)


if __name__ == "__main__":
    unittest.main()
