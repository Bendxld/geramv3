"""Subida de archivos y carpetas al workspace: límites y contención."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.workspace_upload import MAX_UPLOAD_BYTES
from app.core.workspace import MAX_FILE_BYTES, WorkspaceError, WorkspaceService


ROOT = Path(__file__).resolve().parent.parent
UPLOAD_JS = ROOT / "static/workspace-upload.js"
INDEX_HTML = ROOT / "static/index.html"
CHROME_JS = ROOT / "static/vscode-chrome.js"
STYLE_CSS = ROOT / "static/style.css"


class BinaryCreateTests(unittest.TestCase):
    """create_binary_file comparte todas las defensas de create_file."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = WorkspaceService(self.root)

    def test_writes_binary_content_and_reports_it_as_not_editable(self):
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        result = self.service.create_binary_file("assets/logo.png", data, MAX_UPLOAD_BYTES)
        self.assertEqual(result["path"], "assets/logo.png")
        self.assertEqual(result["size"], len(data))
        self.assertFalse(result["editable"])
        self.assertEqual((self.root / "assets/logo.png").read_bytes(), data)

    def test_text_upload_is_marked_editable(self):
        result = self.service.create_binary_file("src/app.py", b"print('hi')\n", MAX_UPLOAD_BYTES)
        self.assertTrue(result["editable"])

    def test_large_but_valid_text_is_not_editable_beyond_the_editor_limit(self):
        data = b"a" * (MAX_FILE_BYTES + 1)
        result = self.service.create_binary_file("big.txt", data, MAX_UPLOAD_BYTES)
        self.assertFalse(result["editable"])

    def test_traversal_cannot_escape_the_workspace(self):
        outside = self.root.parent / "robado.txt"
        for candidate in ("../robado.txt", "a/../../robado.txt", "/etc/passwd"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(WorkspaceError):
                    self.service.create_binary_file(candidate, b"x", MAX_UPLOAD_BYTES)
        self.assertFalse(outside.exists())

    def test_an_existing_file_is_never_overwritten(self):
        self.service.create_binary_file("nota.txt", b"original", MAX_UPLOAD_BYTES)
        with self.assertRaises(WorkspaceError) as caught:
            self.service.create_binary_file("nota.txt", b"pisado", MAX_UPLOAD_BYTES)
        self.assertEqual(caught.exception.code, "file_exists")
        self.assertEqual((self.root / "nota.txt").read_bytes(), b"original")

    def test_a_symlink_in_the_path_is_not_followed(self):
        outside = Path(self.temporary.name).parent / "objetivo"
        outside.mkdir(exist_ok=True)
        self.addCleanup(lambda: outside.rmdir() if outside.is_dir() else None)
        (self.root / "enlace").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            self.service.create_binary_file("enlace/colado.txt", b"x", MAX_UPLOAD_BYTES)
        self.assertFalse((outside / "colado.txt").exists())

    def test_oversized_upload_is_refused(self):
        with self.assertRaises(WorkspaceError) as caught:
            self.service.create_binary_file("grande.bin", b"x" * 11, 10)
        self.assertEqual(caught.exception.code, "file_too_large")


class UploadEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

        from app.api import workspace as workspace_api

        self.service = workspace_api.workspace_service
        self.original_root = self.service.root
        self.service.root = self.root
        self.addCleanup(setattr, self.service, "root", self.original_root)

        from app.core.security import require_localhost
        from app.main import app

        app.dependency_overrides[require_localhost] = lambda: None
        self.addCleanup(app.dependency_overrides.pop, require_localhost, None)
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")
        self.headers = {"Origin": "http://127.0.0.1:8000"}

    def test_uploading_a_file_creates_it_under_the_workspace(self):
        response = self.client.post(
            "/api/workspace/upload",
            params={"path": "docs/nota.md"},
            content=b"# hola\n",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "docs/nota.md")
        self.assertEqual((self.root / "docs/nota.md").read_text(encoding="utf-8"), "# hola\n")

    def test_folder_structure_is_preserved(self):
        for relative in ("proyecto/src/app.py", "proyecto/README.md"):
            response = self.client.post(
                "/api/workspace/upload",
                params={"path": relative},
                content=b"x",
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, relative)
        self.assertTrue((self.root / "proyecto/src/app.py").is_file())
        self.assertTrue((self.root / "proyecto/README.md").is_file())

    def test_traversal_is_refused_over_http(self):
        for candidate in ("../escapado.txt", "a/../../escapado.txt", "/etc/passwd"):
            with self.subTest(candidate=candidate):
                response = self.client.post(
                    "/api/workspace/upload",
                    params={"path": candidate},
                    content=b"x",
                    headers=self.headers,
                )
                # 403 invalid_path: WorkspaceService trata salirse de la raíz
                # como prohibido, no como petición malformada.
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["detail"]["code"], "invalid_path")
        self.assertFalse((self.root.parent / "escapado.txt").exists())

    def test_duplicate_upload_reports_conflict_instead_of_overwriting(self):
        self.client.post(
            "/api/workspace/upload", params={"path": "a.txt"}, content=b"1", headers=self.headers
        )
        second = self.client.post(
            "/api/workspace/upload", params={"path": "a.txt"}, content=b"2", headers=self.headers
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"]["code"], "file_exists")
        self.assertEqual((self.root / "a.txt").read_bytes(), b"1")

    def test_empty_body_is_refused(self):
        response = self.client.post(
            "/api/workspace/upload", params={"path": "vacio.txt"}, content=b"", headers=self.headers
        )
        self.assertEqual(response.status_code, 422)

    def test_a_lying_content_length_cannot_smuggle_a_huge_file(self):
        response = self.client.post(
            "/api/workspace/upload",
            params={"path": "grande.bin"},
            content=b"x",
            headers={**self.headers, "Content-Length": str(MAX_UPLOAD_BYTES + 1)},
        )
        self.assertEqual(response.status_code, 413)

    def test_external_origin_is_rejected(self):
        response = self.client.post(
            "/api/workspace/upload",
            params={"path": "x.txt"},
            content=b"x",
            headers={"Origin": "https://evil.invalid"},
        )
        self.assertEqual(response.status_code, 403)


class UploadFrontendTests(unittest.TestCase):
    def setUp(self):
        self.source = UPLOAD_JS.read_text(encoding="utf-8")

    def test_script_is_loaded(self):
        self.assertIn('<script src="workspace-upload.js"></script>', INDEX_HTML.read_text(encoding="utf-8"))

    def test_no_html_injection_sinks(self):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(sink, self.source)

    def test_folder_uploads_keep_their_structure(self):
        self.assertIn("webkitRelativePath", self.source)
        self.assertIn("webkitdirectory", self.source)

    def test_drag_and_drop_ignores_internal_tree_drags(self):
        # Mover archivos dentro del árbol tiene su propio flujo con aprobación:
        # la subida sólo debe reaccionar a archivos que vienen del sistema.
        self.assertIn("'Files'", self.source)

    def test_client_side_caps_exist_so_a_huge_folder_is_not_a_request_storm(self):
        self.assertIn("MAX_ARCHIVOS", self.source)
        self.assertIn("MAX_BYTES", self.source)

    def test_menu_offers_both_files_and_folder(self):
        chrome = CHROME_JS.read_text(encoding="utf-8")
        self.assertIn("Upload Files…", chrome)
        self.assertIn("Upload Folder…", chrome)
        self.assertIn("GeramWorkspaceUpload", chrome)

    def test_drop_zone_has_a_visible_state(self):
        self.assertIn("subiendo-encima", self.source)
        self.assertIn(".workspace-arbol.subiendo-encima", STYLE_CSS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
