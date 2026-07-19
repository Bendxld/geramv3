"""Selector de carpeta de trabajo: validación, persistencia y cambio en caliente."""

import json
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.core import workspace_root as workspace_root_store


ROOT = Path(__file__).resolve().parent.parent
OPEN_FOLDER_JS = ROOT / "static/open-folder.js"
INDEX_HTML = ROOT / "static/index.html"
STYLE_CSS = ROOT / "static/style.css"
CHROME_JS = ROOT / "static/vscode-chrome.js"


class WorkspaceRootValidationTests(unittest.TestCase):
    def test_rejects_roots_that_would_expose_the_whole_machine(self):
        for value in ("/", str(Path.home()), "/etc", "/usr"):
            with self.subTest(value=value):
                with self.assertRaises(workspace_root_store.WorkspaceRootError):
                    workspace_root_store.validate_candidate(value)

    def test_rejects_empty_and_null_bytes(self):
        for value in ("", "   ", "/tmp/a\x00b"):
            with self.subTest(value=value):
                with self.assertRaises(workspace_root_store.WorkspaceRootError):
                    workspace_root_store.validate_candidate(value)

    def test_rejects_the_public_static_tree(self):
        with self.assertRaises(workspace_root_store.WorkspaceRootError):
            workspace_root_store.validate_candidate(str(ROOT / "static"))

    def test_accepts_an_ordinary_project_folder(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "mi-proyecto"
            project.mkdir()
            self.assertEqual(
                workspace_root_store.validate_candidate(str(project)),
                project.resolve(),
            )


class WorkspaceRootBrowseTests(unittest.TestCase):
    def test_lists_only_directories_and_hides_dotfiles(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "visible").mkdir()
            (base / ".oculta").mkdir()
            (base / "archivo.txt").write_text("x", encoding="utf-8")
            result = workspace_root_store.browse(str(base))
            names = [entry["name"] for entry in result["folders"]]
            self.assertEqual(names, ["visible"])
            self.assertEqual(result["path"], str(base.resolve()))
            self.assertTrue(result["parent"])

    def test_missing_folder_is_reported_and_not_silently_empty(self):
        with self.assertRaises(workspace_root_store.WorkspaceRootError) as caught:
            workspace_root_store.browse("/no/existe/en/ningun/sitio")
        self.assertEqual(caught.exception.code, "folder_not_found")

    def test_browse_marks_unusable_folders_so_the_ui_can_disable_open(self):
        self.assertFalse(workspace_root_store.browse(str(Path.home()))["usable"])


class WorkspaceRootApiTests(unittest.TestCase):
    """El endpoint completo, incluida la conmutación en caliente del explorador."""

    def setUp(self):
        import tempfile

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "proyecto"
        (self.project / "src").mkdir(parents=True)
        (self.project / "src" / "app.py").write_text("print('hola')\n", encoding="utf-8")

        from app.api import workspace as workspace_api

        self.workspace_service = workspace_api.workspace_service
        self.original_root = self.workspace_service.root
        self.addCleanup(setattr, self.workspace_service, "root", self.original_root)

        from app.core.config import settings

        self.settings = settings
        self.original_settings_root = settings.WORKSPACE_ROOT
        self.addCleanup(setattr, settings, "WORKSPACE_ROOT", self.original_settings_root)

        # El estado se guarda en un directorio temporal: la prueba no debe
        # tocar la carpeta real que el usuario tenga abierta.
        self.state_path = Path(self.temporary.name) / "workspace-root.json"
        patcher = mock.patch.object(
            workspace_root_store, "_state_path", return_value=self.state_path
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        from app.main import app
        from app.core.security import require_localhost

        # Mismo patrón que el resto de las pruebas de API: TestClient no tiene
        # un peer 127.0.0.1 real, así que se anula la guarda de localhost. La
        # protección en sí se cubre en test_security.py.
        app.dependency_overrides[require_localhost] = lambda: None
        self.addCleanup(app.dependency_overrides.pop, require_localhost, None)
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def _headers(self):
        return {"Origin": "http://127.0.0.1:8000"}

    def test_opening_a_folder_repoints_the_explorer_and_persists(self):
        response = self.client.post(
            "/api/workspace/root",
            json={"path": str(self.project)},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], str(self.project.resolve()))

        # El explorador ya lista los archivos de la carpeta nueva.
        tree = self.client.get("/api/workspace/tree")
        self.assertEqual(tree.status_code, 200)
        paths = {entry["path"] for entry in tree.json()["entries"]}
        self.assertIn("src/app.py", paths)

        # Y la elección quedó escrita para el próximo arranque.
        stored = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["path"], str(self.project.resolve()))
        self.assertEqual(workspace_root_store.load_saved(), self.project.resolve())

    def test_unsafe_folders_are_refused_without_changing_the_workspace(self):
        before = self.workspace_service.root
        response = self.client.post(
            "/api/workspace/root",
            json={"path": str(Path.home())},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "unsafe_workspace_root")
        self.assertEqual(self.workspace_service.root, before)
        self.assertFalse(self.state_path.exists())

    def test_missing_folder_returns_404(self):
        response = self.client.post(
            "/api/workspace/root",
            json={"path": "/no/existe/en/ningun/sitio"},
            headers=self._headers(),
        )
        self.assertIn(response.status_code, (404, 422))
        self.assertFalse(self.state_path.exists())

    def test_saved_root_that_disappeared_is_ignored_instead_of_breaking_startup(self):
        workspace_root_store.save(self.project)
        self.assertIsNotNone(workspace_root_store.load_saved())
        import shutil

        shutil.rmtree(self.project)
        self.assertIsNone(workspace_root_store.load_saved())

    def test_explicit_configuration_wins_over_the_saved_choice(self):
        """GERAM_WORKSPACE_ROOT manda: despliegues y pruebas fijan esa carpeta
        y la elección guardada del HUD no debe pisarla."""
        from app.core.config import Settings

        explicit = Path(self.temporary.name) / "explicita"
        explicit.mkdir()
        configured = Settings(
            {"GERAM_WORKSPACE_ROOT": str(explicit)}, create_runtime_dirs=False
        )
        self.assertTrue(configured.WORKSPACE_ROOT_IS_EXPLICIT)
        self.assertEqual(configured.WORKSPACE_ROOT, explicit.resolve())

        default = Settings({}, create_runtime_dirs=False)
        self.assertFalse(default.WORKSPACE_ROOT_IS_EXPLICIT)

    def test_browse_endpoint_walks_the_disk(self):
        response = self.client.get(
            "/api/workspace/root/browse", params={"path": str(self.project)}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([entry["name"] for entry in body["folders"]], ["src"])
        self.assertTrue(body["usable"])


class OpenFolderFrontendTests(unittest.TestCase):
    """El selector se carga, no inyecta HTML y está enganchado al menú."""

    def setUp(self):
        self.source = OPEN_FOLDER_JS.read_text(encoding="utf-8")

    def test_script_is_loaded_before_the_chrome_that_calls_it(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('<script src="open-folder.js"></script>', html)
        # Comparamos las etiquetas <script>, no cualquier mención: el HTML
        # nombra vscode-chrome.js en comentarios mucho antes de cargarlo.
        self.assertLess(
            html.index('<script src="open-folder.js">'),
            html.index('<script src="vscode-chrome.js">'),
        )

    def test_folder_names_never_reach_the_dom_as_html(self):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(sink, self.source)
        self.assertIn("textContent", self.source)

    def test_menu_exposes_open_folder_and_keeps_the_explorer_toggle(self):
        chrome = CHROME_JS.read_text(encoding="utf-8")
        self.assertIn("Open Folder…", chrome)
        self.assertIn("GeramOpenFolder", chrome)
        self.assertIn("Toggle Explorer", chrome)

    def test_open_is_blocked_for_folders_the_backend_marks_unusable(self):
        self.assertIn("openButton.disabled = !currentUsable", self.source)
        self.assertIn("if (!currentPath || !currentUsable) { return; }", self.source)

    def test_explorer_is_reloaded_after_switching_folders(self):
        self.assertIn("reloadTree", self.source)

    def test_styles_exist_and_long_paths_cannot_overflow_the_dialog(self):
        css = STYLE_CSS.read_text(encoding="utf-8")
        self.assertIn(".of-caja", css)
        self.assertIn(".of-ruta", css)
        self.assertIn("overflow-wrap: anywhere", css)


if __name__ == "__main__":
    unittest.main()
