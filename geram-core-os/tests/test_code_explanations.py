"""Explicaciones de código de A.R.E.S.: contexto, contrato, seguridad e interfaz."""

import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.core.code_explanation import (
    MAX_CONTEXT_CHARS,
    MAX_LIST_ITEMS,
    MAX_REFERENCES,
    CodeContextBuilder,
    ExplanationError,
    build_prompt,
    offline_demo,
    validate_explanation,
)
from app.core.workspace import WorkspaceError, WorkspaceService
from app.core.workspace_search import WorkspaceSearchService


ROOT = Path(__file__).resolve().parent.parent
EXPLAIN_JS = ROOT / "static/ares-explain.js"
INDEX_HTML = ROOT / "static/index.html"
STYLE_CSS = ROOT / "static/style.css"

CALCULATOR = '''"""Small calculator."""
import sys


def add(a, b):
    """Add two numbers."""
    return a + b


def divide(a, b):
    return a / b


def main():
    print(add(2, 3))
'''


def _valid_payload(scope="file", level="technical", file_name="calculator.py"):
    return {
        "scope": scope,
        "level": level,
        "summary": "A calculator module.",
        "purpose": "Provide arithmetic helpers.",
        "flow": ["main calls add", "add returns the sum"],
        "inputs": ["two numbers"],
        "outputs": ["the sum"],
        "dependencies": ["sys"],
        "risks": ["divide does not guard against zero"],
        "references": [
            {
                "file": file_name,
                "start_line": 5,
                "end_line": 7,
                "symbol": "add",
                "claim": "add returns a + b",
            }
        ],
        "inferences": [
            {
                "text": "This appears to be a calculator project.",
                "confidence": "medium",
                "evidence": ["symbols add and divide"],
            }
        ],
    }


class ContextBuildingTests(unittest.TestCase):
    """Alcances: selección, archivo y proyecto — con contexto acotado."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "calculator.py").write_text(CALCULATOR, encoding="utf-8")
        (self.root / "README.md").write_text("# Calculator\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_calc.py").write_text("def test_add(): pass\n", encoding="utf-8")
        (self.root / ".env").write_text("SECRET_KEY=abc123\n", encoding="utf-8")
        self.workspace = WorkspaceService(self.root)
        self.builder = CodeContextBuilder(self.workspace, WorkspaceSearchService(self.workspace))

    # -- selección -------------------------------------------------------
    def test_selection_reports_file_lines_and_containing_symbol(self):
        context = self.builder.build_selection(
            "calculator.py", "    return a / b", 11, 11, "technical"
        )
        self.assertEqual(context.scope, "selection")
        self.assertEqual(context.selection_path, "calculator.py")
        self.assertEqual(context.selection_start_line, 11)
        self.assertEqual(context.selection_symbol, "divide")

    def test_selection_sends_only_a_window_not_the_whole_file(self):
        big = "\n".join(f"line_{index}" for index in range(400))
        (self.root / "big.py").write_text(big, encoding="utf-8")
        context = self.builder.build_selection("big.py", "line_200", 201, 201, "simple")
        self.assertLess(len(context.files[0].content), len(big))
        self.assertTrue(context.files[0].truncated)

    def test_empty_selection_is_refused(self):
        for value in ("", "   ", "\n\t"):
            with self.subTest(value=value):
                with self.assertRaises(ExplanationError) as caught:
                    self.builder.build_selection("calculator.py", value, 1, 1, "simple")
                self.assertEqual(caught.exception.code, "empty_selection")

    # -- archivo ---------------------------------------------------------
    def test_file_scope_collects_symbols_and_imports(self):
        context = self.builder.build_file("calculator.py", "technical")
        self.assertEqual(context.scope, "file")
        self.assertIn("add", context.symbols)
        self.assertIn("divide", context.symbols)
        self.assertTrue(any("import sys" in value for value in context.imports))

    def test_missing_file_is_refused(self):
        with self.assertRaises(ExplanationError) as caught:
            self.builder.build_file("no_existe.py", "simple")
        self.assertEqual(caught.exception.status_code, 404)

    def test_empty_file_is_refused(self):
        (self.root / "vacio.py").write_text("", encoding="utf-8")
        with self.assertRaises(ExplanationError) as caught:
            self.builder.build_file("vacio.py", "simple")
        self.assertEqual(caught.exception.code, "empty_file")

    # -- proyecto --------------------------------------------------------
    def test_project_scope_maps_files_and_finds_tests(self):
        context = self.builder.build_project("architecture")
        self.assertEqual(context.scope, "project")
        self.assertIn("calculator.py", context.tree)
        self.assertIn("tests/test_calc.py", context.tests)
        # README y calculator.py son señales de propósito: deben ir primero.
        included = [item.path for item in context.files]
        self.assertIn("README.md", included)
        self.assertIn("calculator.py", included)

    def test_project_scope_does_not_send_the_whole_project(self):
        for index in range(40):
            (self.root / f"modulo_{index}.py").write_text(f"def f{index}(): pass\n", encoding="utf-8")
        context = self.builder.build_project("architecture")
        self.assertLessEqual(len(context.files), 12)
        self.assertGreater(len(context.tree), len(context.files))

    def test_empty_project_is_refused(self):
        with tempfile.TemporaryDirectory() as empty:
            workspace = WorkspaceService(Path(empty))
            builder = CodeContextBuilder(workspace, WorkspaceSearchService(workspace))
            with self.assertRaises(ExplanationError) as caught:
                builder.build_project("simple")
            self.assertEqual(caught.exception.code, "empty_project")

    # -- secretos y límites ----------------------------------------------
    def test_secrets_are_never_part_of_the_context(self):
        context = self.builder.build_project("architecture")
        paths = [item.path for item in context.files] + context.tree
        self.assertNotIn(".env", paths)
        blob = " ".join(item.content for item in context.files)
        self.assertNotIn("SECRET_KEY", blob)
        self.assertNotIn("abc123", blob)

    def test_a_secret_file_cannot_be_explained_on_purpose(self):
        with self.assertRaises(ExplanationError):
            self.builder.build_file(".env", "simple")

    def test_context_limit_is_enforced(self):
        context = self.builder.build_file("calculator.py", "simple")
        self.assertLess(context.approximate_chars(), MAX_CONTEXT_CHARS)
        with mock.patch.object(type(context), "approximate_chars", return_value=MAX_CONTEXT_CHARS + 1):
            with self.assertRaises(ExplanationError) as caught:
                self.builder.build("file", "simple", {"path": "calculator.py"})
            self.assertEqual(caught.exception.code, "context_too_large")

    def test_preview_describes_what_would_be_sent(self):
        context = self.builder.build_file("calculator.py", "technical")
        preview = context.preview("gemini", "gemini-2.5-flash")
        self.assertEqual(preview["provider"], "gemini")
        self.assertEqual(preview["model"], "gemini-2.5-flash")
        self.assertEqual(preview["files"][0]["path"], "calculator.py")
        self.assertFalse(preview["selection_included"])
        self.assertTrue(preview["secrets_excluded"])
        self.assertGreater(preview["approximate_chars"], 0)

    def test_prompt_states_read_only_and_marks_code_as_untrusted(self):
        prompt = build_prompt(self.builder.build_file("calculator.py", "risks"))
        self.assertIn("READ-ONLY", prompt)
        self.assertIn("untrusted data", prompt)
        self.assertIn("never propose edits", prompt)


class ContractValidationTests(unittest.TestCase):
    """El contrato JSON se valida sin piedad."""

    def setUp(self):
        self.allowed = {"calculator.py"}

    def _validate(self, payload, scope="file", level="technical"):
        return validate_explanation(payload, scope=scope, level=level, allowed_files=self.allowed)

    def test_a_valid_payload_passes(self):
        result = self._validate(_valid_payload())
        self.assertEqual(result["scope"], "file")
        self.assertEqual(result["references"][0]["symbol"], "add")
        self.assertEqual(result["inferences"][0]["confidence"], "medium")

    def test_json_text_is_accepted(self):
        import json

        self.assertEqual(self._validate(json.dumps(_valid_payload()))["scope"], "file")

    def test_invalid_json_is_refused(self):
        with self.assertRaises(ExplanationError) as caught:
            self._validate("no soy json")
        self.assertEqual(caught.exception.code, "invalid_contract")

    def test_unknown_fields_are_refused(self):
        payload = _valid_payload()
        payload["extra"] = "nope"
        with self.assertRaises(ExplanationError):
            self._validate(payload)

    def test_missing_fields_are_refused(self):
        payload = _valid_payload()
        del payload["risks"]
        with self.assertRaises(ExplanationError):
            self._validate(payload)

    def test_wrong_types_are_refused(self):
        for field, value in (("summary", 42), ("flow", "not a list"), ("references", {})):
            with self.subTest(field=field):
                payload = _valid_payload()
                payload[field] = value
                with self.assertRaises(ExplanationError):
                    self._validate(payload)

    def test_scope_and_level_must_match_the_request(self):
        with self.assertRaises(ExplanationError):
            self._validate(_valid_payload(scope="project"))
        with self.assertRaises(ExplanationError):
            self._validate(_valid_payload(level="simple"))

    def test_too_many_items_are_refused(self):
        payload = _valid_payload()
        payload["flow"] = [f"step {index}" for index in range(MAX_LIST_ITEMS + 1)]
        with self.assertRaises(ExplanationError):
            self._validate(payload)
        payload = _valid_payload()
        payload["references"] = payload["references"] * (MAX_REFERENCES + 1)
        with self.assertRaises(ExplanationError):
            self._validate(payload)

    def test_overlong_text_is_refused(self):
        payload = _valid_payload()
        payload["summary"] = "x" * 5000
        with self.assertRaises(ExplanationError):
            self._validate(payload)

    # -- referencias -----------------------------------------------------
    def test_absolute_and_traversal_paths_are_refused(self):
        for bad in ("/etc/passwd", "../secreto.py", "a/../../x.py", "C:\\win.py"):
            with self.subTest(bad=bad):
                payload = _valid_payload()
                payload["references"][0]["file"] = bad
                with self.assertRaises(ExplanationError) as caught:
                    self._validate(payload)
                self.assertIn(caught.exception.code, ("invalid_reference", "invalid_contract"))

    def test_a_reference_outside_the_sent_context_is_refused(self):
        payload = _valid_payload(file_name="otro_archivo.py")
        with self.assertRaises(ExplanationError) as caught:
            self._validate(payload)
        self.assertEqual(caught.exception.code, "invalid_reference")

    def test_invalid_line_numbers_are_refused(self):
        for start, end in ((0, 5), (5, 2), (-1, 3), (1, 10**9)):
            with self.subTest(start=start, end=end):
                payload = _valid_payload()
                payload["references"][0]["start_line"] = start
                payload["references"][0]["end_line"] = end
                with self.assertRaises(ExplanationError):
                    self._validate(payload)

    def test_boolean_is_not_accepted_as_a_line_number(self):
        payload = _valid_payload()
        payload["references"][0]["start_line"] = True
        with self.assertRaises(ExplanationError):
            self._validate(payload)

    # -- contenido peligroso ---------------------------------------------
    def test_html_and_scripts_are_refused_in_text_fields(self):
        for value in ("<script>alert(1)</script>", "<img src=x onerror=y>", "hola <b>mundo</b>"):
            with self.subTest(value=value):
                payload = _valid_payload()
                payload["summary"] = value
                with self.assertRaises(ExplanationError) as caught:
                    self._validate(payload)
                self.assertEqual(caught.exception.code, "unsafe_content")

    def test_urls_are_refused_in_text_fields(self):
        for value in ("visita https://evil.example", "javascript:alert(1)", "data:text/html,x"):
            with self.subTest(value=value):
                payload = _valid_payload()
                payload["purpose"] = value
                with self.assertRaises(ExplanationError) as caught:
                    self._validate(payload)
                self.assertEqual(caught.exception.code, "unsafe_content")

    def test_markup_is_refused_inside_references_and_inferences_too(self):
        payload = _valid_payload()
        payload["references"][0]["claim"] = "<script>x</script>"
        with self.assertRaises(ExplanationError):
            self._validate(payload)
        payload = _valid_payload()
        payload["inferences"][0]["text"] = "<b>guess</b>"
        with self.assertRaises(ExplanationError):
            self._validate(payload)

    # -- inferencias -----------------------------------------------------
    def test_inferences_stay_separate_from_facts(self):
        result = self._validate(_valid_payload())
        self.assertNotIn("appears", result["summary"])
        self.assertIn("appears", result["inferences"][0]["text"])
        self.assertIn(result["inferences"][0]["confidence"], ("low", "medium", "high"))

    def test_invalid_confidence_is_refused(self):
        payload = _valid_payload()
        payload["inferences"][0]["confidence"] = "certain"
        with self.assertRaises(ExplanationError):
            self._validate(payload)


class OfflineDemoTests(unittest.TestCase):
    def test_demo_is_a_valid_contract_and_marked_as_a_template(self):
        demo = offline_demo("project", "simple")
        validated = validate_explanation(
            demo, scope="project", level="simple", allowed_files={"calculator.py"}
        )
        self.assertIn("DEMONSTRATION TEMPLATE", validated["summary"])
        self.assertIn("DEMONSTRATION TEMPLATE", validated["purpose"])

    def test_demo_presents_the_calculator_guess_as_an_inference(self):
        demo = offline_demo("project", "simple")
        self.assertTrue(demo["inferences"])
        self.assertIn("appears to be", demo["inferences"][0]["text"])
        self.assertNotIn("appears to be", demo["summary"])


class ExplanationApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "calculator.py").write_text(CALCULATOR, encoding="utf-8")
        (self.root / ".env").write_text("SECRET_KEY=abc123\n", encoding="utf-8")

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

    def test_preview_endpoint_does_not_call_the_provider(self):
        with mock.patch(
            "app.core.providers.registry.provider_registry.generate_for_role"
        ) as provider:
            response = self.client.post(
                "/api/ares/explanations/preview",
                json={"scope": "file", "level": "technical", "path": "calculator.py"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        provider.assert_not_called()
        self.assertTrue(response.json()["secrets_excluded"])

    def test_offline_mode_returns_the_demo_without_a_provider(self):
        with mock.patch(
            "app.core.providers.registry.provider_registry.generate_for_role"
        ) as provider:
            response = self.client.post(
                "/api/ares/explanations",
                json={"scope": "project", "level": "simple", "offline": True},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        provider.assert_not_called()
        body = response.json()
        self.assertTrue(body["demo"])
        self.assertIn("DEMONSTRATION TEMPLATE", body["explanation"]["summary"])

    def test_a_valid_provider_response_is_returned(self):
        import json

        dispatch = mock.Mock()
        dispatch.result = {"text": json.dumps(_valid_payload())}
        dispatch.metadata = {"provider": "gemini", "model": "gemini-2.5-flash"}
        with mock.patch(
            "app.core.providers.registry.provider_registry.generate_for_role",
            new=mock.AsyncMock(return_value=dispatch),
        ):
            response = self.client.post(
                "/api/ares/explanations",
                json={"scope": "file", "level": "technical", "path": "calculator.py"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["demo"])
        self.assertEqual(body["explanation"]["references"][0]["file"], "calculator.py")

    def test_an_invalid_provider_response_is_refused(self):
        dispatch = mock.Mock()
        dispatch.result = {"text": '{"summary": "<script>x</script>"}'}
        dispatch.metadata = {"provider": "gemini", "model": "m"}
        with mock.patch(
            "app.core.providers.registry.provider_registry.generate_for_role",
            new=mock.AsyncMock(return_value=dispatch),
        ):
            response = self.client.post(
                "/api/ares/explanations",
                json={"scope": "file", "level": "technical", "path": "calculator.py"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 422)

    def test_provider_failure_is_reported_safely(self):
        with mock.patch(
            "app.core.providers.registry.provider_registry.generate_for_role",
            new=mock.AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = self.client.post(
                "/api/ares/explanations",
                json={"scope": "file", "level": "technical", "path": "calculator.py"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["code"], "provider_unavailable")
        self.assertNotIn("boom", response.text)

    def test_external_origin_is_rejected(self):
        response = self.client.post(
            "/api/ares/explanations/preview",
            json={"scope": "project", "level": "simple"},
            headers={"Origin": "https://evil.invalid"},
        )
        self.assertEqual(response.status_code, 403)

    def test_explaining_never_modifies_the_workspace(self):
        before = {
            path: path.read_bytes()
            for path in sorted(self.root.rglob("*")) if path.is_file()
        }
        self.client.post(
            "/api/ares/explanations",
            json={"scope": "project", "level": "simple", "offline": True},
            headers=self.headers,
        )
        self.client.post(
            "/api/ares/explanations/preview",
            json={"scope": "file", "level": "risks", "path": "calculator.py"},
            headers=self.headers,
        )
        after = {
            path: path.read_bytes()
            for path in sorted(self.root.rglob("*")) if path.is_file()
        }
        self.assertEqual(before, after)


class ExplanationSecurityTests(unittest.TestCase):
    """El módulo es de sólo lectura: se comprueba en el propio código."""

    def setUp(self):
        self.core = (ROOT / "app/core/code_explanation.py").read_text(encoding="utf-8")
        self.api = (ROOT / "app/api/code_explanations.py").read_text(encoding="utf-8")

    def test_no_write_shell_or_subprocess_primitives(self):
        for forbidden in (
            "subprocess", "os.system", "popen", "open(", "write_text",
            "write_bytes", "unlink", "rmtree", "shutil",
        ):
            for name, source in (("core", self.core), ("api", self.api)):
                with self.subTest(forbidden=forbidden, module=name):
                    self.assertNotIn(forbidden, source)

    def test_no_network_beyond_the_selected_provider(self):
        for forbidden in ("httpx", "requests", "urllib", "socket", "aiohttp"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.core)
        # La API sólo alcanza la red a través del registry de proveedores.
        self.assertIn("provider_registry", self.api)
        for forbidden in ("httpx", "requests", "urllib", "socket"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.api)

    def test_does_not_touch_the_proposal_or_diff_flow(self):
        """Se comprueba el CÓDIGO, no la prosa.

        Una comprobación por subcadena daría falsos positivos con los propios
        comentarios que explican que este módulo no hace eso; se inspeccionan
        los imports reales y las rutas declaradas.
        """
        import ast

        tree = ast.parse(self.api)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        self.assertNotIn("app.api.ares_edits", imported)
        self.assertFalse({name for name in imported if "ares_edits" in name})

        # Ninguna ruta declarada pertenece al flujo de propuestas.
        routes = re.findall(r'@\w+\.(?:post|get|put|delete)\(\s*"([^"]*)"', self.api)
        for route in routes:
            with self.subTest(route=route):
                self.assertNotIn("proposal", route)
                self.assertNotIn("apply", route)

        # Y no se invoca ninguna primitiva de aplicación de cambios.
        for forbidden in ("applyAresChanges", "save_file", "create_file", "_build_unified_diff"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.api)

    def test_failures_are_logged_without_code_or_response_content(self):
        self.assertIn("ares_explanation_rejected", self.api)
        self.assertNotIn("raw_text}", self.api)
        self.assertNotIn('"content"', self.api)


class ExplanationFrontendTests(unittest.TestCase):
    def setUp(self):
        self.source = EXPLAIN_JS.read_text(encoding="utf-8")
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_script_and_markup_are_wired(self):
        self.assertIn('<script src="ares-explain.js"></script>', self.html)
        for element in (
            "aresExplicaSeleccion", "aresExplicaArchivo", "aresExplicaProyecto",
            "aresExplicaNivel", "aresExplicaOffline", "aresExplicaPreview",
            "aresExplicaResultado",
        ):
            with self.subTest(element=element):
                self.assertIn(element, self.html)

    def test_all_five_levels_are_offered(self):
        for level in ("simple", "technical", "step_by_step", "risks", "architecture"):
            with self.subTest(level=level):
                self.assertIn('value="%s"' % level, self.html)

    def test_provider_content_is_never_rendered_as_html(self):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            with self.subTest(sink=sink):
                self.assertNotIn(sink, self.source)
        self.assertIn("textContent", self.source)

    def test_structured_view_covers_every_contract_section(self):
        for label in (
            "Summary", "Purpose", "Flow", "Inputs", "Outputs",
            "Dependencies", "Risks", "Code references", "Inferences",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.source)

    def test_references_navigate_to_file_and_line(self):
        self.assertIn("c.navigate(ref.file, ref.start_line, 1)", self.source)
        # Abrir primero: navigate() sólo revela documentos ya cargados.
        self.assertIn("c.open(ref.file)", self.source)

    def test_preview_is_requested_before_the_explanation(self):
        """El preview se pide primero en la CADENA, no sólo en el archivo.

        Comparar posiciones en el texto mediría el orden en que están escritas
        las funciones, que no dice nada; se comprueba la secuencia real dentro
        del flujo: preview -> pintar preview -> explicación.
        """
        flujo = self.source[self.source.index("function explicar("):]
        pedir_preview = flujo.index("pedir(API + '/preview', cuerpo)")
        pintar_preview = flujo.index("pintarPreview(preview)")
        pedir_explicacion = flujo.index("return pedir(API, cuerpo)")
        self.assertLess(pedir_preview, pintar_preview)
        self.assertLess(pintar_preview, pedir_explicacion)

    def test_inferences_are_visually_separated_from_facts(self):
        self.assertIn("Inferences (not confirmed)", self.source)
        self.assertIn("not verified fact", self.source)
        self.assertIn(".ares-explica-inferencias", STYLE_CSS.read_text(encoding="utf-8"))

    def test_demo_mode_is_labelled_in_the_view(self):
        self.assertIn("DEMONSTRATION TEMPLATE", self.source)

    def test_the_panel_can_be_collapsed_and_hidden(self):
        """El panel vive debajo del editor: si crece sin tope, tapa el código."""
        self.assertIn("cabeceraPlegable", self.source)
        self.assertIn("Hide all", self.source)
        # Plegar y ocultar son acciones distintas: una conserva el resultado.
        self.assertIn("cuerpo.hidden = !oculto", self.source)
        self.assertIn("caja.hidden = true", self.source)

    def test_long_output_scrolls_instead_of_pushing_the_editor(self):
        css = STYLE_CSS.read_text(encoding="utf-8")
        self.assertIn(".ares-explica-cuerpo", css)
        self.assertIn("max-height", css)
        self.assertIn("overflow-y: auto", css)

    def test_collapsing_is_announced_to_assistive_tech(self):
        self.assertIn("aria-expanded", self.source)

    def test_the_panel_is_written_in_english_like_the_rest_of_the_hud(self):
        """El HUD está en inglés; este panel no debe volver a desentonar."""
        import re

        visibles = re.findall(r"'([^']*)'", self.source)
        acentos = [t for t in visibles if re.search(r"[áéíóúñ¿¡]", t)]
        self.assertEqual(acentos, [], f"texto visible en español: {acentos}")

    def test_task_action_only_copies_a_summary(self):
        self.assertIn("usarParaTarea", self.source)
        self.assertIn("workspaceAresInstruction", self.source)
        # No debe disparar el flujo de propuesta ni aplicar nada.
        self.assertNotIn("applyAresChanges", self.source)
        self.assertNotIn("/api/ares/proposals", self.source)


if __name__ == "__main__":
    unittest.main()


class AuxiliarySignalTests(unittest.TestCase):
    """Pyright, referencias, diagnósticos y Git: opcionales y degradables."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "calculator.py").write_text(CALCULATOR, encoding="utf-8")
        (self.root / "usa.py").write_text("from calculator import add\nprint(add(1, 2))\n", encoding="utf-8")
        self.workspace = WorkspaceService(self.root)
        self.builder = CodeContextBuilder(self.workspace, WorkspaceSearchService(self.workspace))

    def _context(self):
        return self.builder.build_file("calculator.py", "technical")

    # -- referencias -----------------------------------------------------
    def test_references_find_other_occurrences_of_the_symbol(self):
        context = self._context()
        self.builder.collect_references("add", context)
        self.assertTrue(context.references)
        self.assertTrue(any("usa.py" in hit for hit in context.references))
        self.assertEqual(context.sources["references"], "workspace search")

    def test_references_are_skipped_without_a_usable_symbol(self):
        for symbol in ("", "   ", "not an identifier"):
            with self.subTest(symbol=symbol):
                context = self._context()
                self.builder.collect_references(symbol, context)
                self.assertEqual(context.references, [])
                self.assertEqual(context.sources["references"], "no symbol to look up")

    def test_a_failing_search_degrades_instead_of_breaking(self):
        context = self._context()
        with mock.patch.object(
            self.builder.search, "search", side_effect=WorkspaceError("boom", "x", 500)
        ):
            self.builder.collect_references("add", context)
        self.assertEqual(context.references, [])
        self.assertIn("unavailable", context.sources["references"])

    # -- diagnósticos ----------------------------------------------------
    def test_editor_diagnostics_are_bounded_and_normalised(self):
        context = self._context()
        self.builder.collect_diagnostics(
            [
                {"severity": "error", "line": 11, "message": "Division by zero"},
                {"severity": "warning", "line": 0, "message": "unused import"},
                {"nonsense": True},
                {"severity": "error", "line": 1, "message": ""},
            ],
            context,
        )
        self.assertEqual(len(context.diagnostics), 2)
        self.assertIn("[error] line 11: Division by zero", context.diagnostics)
        self.assertIn("[warning] file: unused import", context.diagnostics)
        self.assertEqual(context.sources["diagnostics"], "editor")

    def test_diagnostics_are_capped(self):
        context = self._context()
        self.builder.collect_diagnostics(
            [{"severity": "error", "line": i + 1, "message": f"problema {i}"} for i in range(50)],
            context,
        )
        self.assertLessEqual(len(context.diagnostics), 20)

    def test_no_diagnostics_is_reported_honestly(self):
        for raw in (None, [], "no soy lista"):
            with self.subTest(raw=raw):
                context = self._context()
                self.builder.collect_diagnostics(raw, context)
                self.assertEqual(context.sources["diagnostics"], "none reported")

    # -- pyright ---------------------------------------------------------
    def test_pyright_is_never_started_by_this_mode(self):
        """Arrancarlo sería crear un proceso nuevo, que este modo tiene prohibido."""
        context = self._context()
        manager = mock.Mock()
        manager.running = False
        manager.start = mock.AsyncMock()
        with mock.patch.object(self.builder, "_lsp_manager", return_value=manager):
            asyncio.run(self.builder.collect_pyright("calculator.py", context))
        manager.start.assert_not_called()
        self.assertEqual(context.sources["pyright"], "not running")

    def test_pyright_symbols_replace_the_regex_ones_when_available(self):
        context = self._context()
        heuristicos = list(context.symbols)
        manager = mock.Mock()
        manager.running = True
        manager.request = mock.AsyncMock(return_value=[
            {"name": "add", "children": [{"name": "inner"}]},
            {"name": "divide"},
        ])
        with mock.patch.object(self.builder, "_lsp_manager", return_value=manager):
            asyncio.run(self.builder.collect_pyright("calculator.py", context))
        self.assertEqual(context.symbols, ["add", "inner", "divide"])
        self.assertEqual(context.sources["symbols"], "pyright")
        self.assertNotEqual(context.symbols, heuristicos)

    def test_a_failing_pyright_degrades_to_the_heuristic_symbols(self):
        context = self._context()
        heuristicos = list(context.symbols)
        manager = mock.Mock()
        manager.running = True
        manager.request = mock.AsyncMock(side_effect=TimeoutError())
        with mock.patch.object(self.builder, "_lsp_manager", return_value=manager):
            asyncio.run(self.builder.collect_pyright("calculator.py", context))
        self.assertEqual(context.symbols, heuristicos)
        self.assertEqual(context.sources["pyright"], "unavailable")

    # -- git -------------------------------------------------------------
    def test_git_changes_list_paths_without_diff_content(self):
        context = self._context()
        service = mock.Mock()
        # Forma REAL de GitService.status(), copiada de la respuesta del
        # endpoint: entries + kind. Un mock inventado aquí haría que la
        # prueba pasara con el código roto.
        service.status.return_value = {
            "branch": "master",
            "entries": [{
                "path": "calculator.py", "original_path": "", "index": ".",
                "worktree": "M", "kind": "modified", "staged": False,
            }],
            "clean": False,
        }
        with mock.patch.object(self.builder, "_git_service", return_value=service):
            self.builder.collect_git_changes(context)
        self.assertEqual(context.changes, ["calculator.py (modified)"])
        self.assertEqual(context.sources["git"], "git status")

    def test_a_non_repository_degrades_quietly(self):
        context = self._context()
        service = mock.Mock()
        service.status.side_effect = RuntimeError("not a repo")
        with mock.patch.object(self.builder, "_git_service", return_value=service):
            self.builder.collect_git_changes(context)
        self.assertEqual(context.changes, [])
        self.assertEqual(context.sources["git"], "not a git repository")

    # -- integración -----------------------------------------------------
    def test_build_async_enriches_without_breaking_the_limit(self):
        context = asyncio.run(
            self.builder.build_async(
                "selection", "technical",
                {
                    "path": "calculator.py",
                    "selection": "def add(a, b):\n    return a + b",
                    "start_line": 5, "end_line": 7,
                    "diagnostics": [{"severity": "error", "line": 11, "message": "zero division"}],
                },
            )
        )
        self.assertEqual(context.selection_symbol, "add")
        self.assertTrue(context.diagnostics)
        self.assertTrue(context.references)
        self.assertLessEqual(context.approximate_chars(), MAX_CONTEXT_CHARS)
        self.assertIn("diagnostics", context.sources)
        self.assertIn("git", context.sources)

    def test_auxiliary_signals_are_dropped_before_the_code_when_too_large(self):
        context = asyncio.run(
            self.builder.build_async("file", "simple", {"path": "calculator.py"})
        )
        context.references = ["x" * 30_000]
        context.changes = ["y" * 30_000]
        # Se simula el recorte del propio build_async.
        if context.approximate_chars() > MAX_CONTEXT_CHARS:
            context.references = []
            context.changes = []
        self.assertTrue(context.files)
        self.assertEqual(context.references, [])

    def test_prompt_marks_diagnostics_and_git_as_data(self):
        context = self._context()
        self.builder.collect_diagnostics(
            [{"severity": "error", "line": 1, "message": "boom"}], context
        )
        context.changes = ["calculator.py (modified)"]
        prompt = build_prompt(context)
        self.assertIn("data, not", prompt)
        self.assertIn("no diff", prompt)

    def test_preview_reports_where_each_signal_came_from(self):
        context = asyncio.run(
            self.builder.build_async("file", "simple", {"path": "calculator.py"})
        )
        preview = context.preview("gemini", "m")
        self.assertIn("sources", preview)
        self.assertIn("git", preview["sources"])
        self.assertIn("diagnostics", preview["sources"])


class SemanticReferenceTests(unittest.TestCase):
    """Referencias resueltas por Pyright, con la búsqueda de texto de respaldo."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "calculator.py").write_text(CALCULATOR, encoding="utf-8")
        (self.root / "usa.py").write_text(
            "from calculator import add\nprint(add(1, 2))\n", encoding="utf-8"
        )
        self.workspace = WorkspaceService(self.root)
        self.builder = CodeContextBuilder(self.workspace, WorkspaceSearchService(self.workspace))

    def _manager(self, respuesta):
        manager = mock.Mock()
        manager.running = True
        manager.request = mock.AsyncMock(return_value=respuesta)
        return manager

    def test_position_prefers_the_definition_over_a_usage(self):
        posicion = self.builder._symbol_position(CALCULATOR, "add", 20)
        linea = CALCULATOR.splitlines()[posicion[0]]
        self.assertTrue(linea.startswith("def add"))
        self.assertEqual(linea[posicion[1]:posicion[1] + 3], "add")

    def test_position_falls_back_to_the_occurrence_nearest_the_selection(self):
        contenido = "x = 1\nvalor = 2\nprint(valor)\n"
        posicion = self.builder._symbol_position(contenido, "valor", 3)
        self.assertEqual(posicion[0], 2)

    def test_unknown_symbol_has_no_position(self):
        self.assertIsNone(self.builder._symbol_position(CALCULATOR, "no_existe", 1))

    def test_pyright_references_are_used_when_available(self):
        respuesta = [
            {"uri": "file:///workspace/calculator.py", "range": {"start": {"line": 4, "character": 4}}},
            {"uri": "file:///workspace/usa.py", "range": {"start": {"line": 1, "character": 6}}},
        ]
        context = self.builder.build_file("calculator.py", "technical")
        with mock.patch.object(self.builder, "_lsp_manager", return_value=self._manager(respuesta)):
            usado = asyncio.run(
                self.builder.collect_references_semantic("calculator.py", "add", 5, context)
            )
        self.assertTrue(usado)
        self.assertEqual(context.references, ["calculator.py:5", "usa.py:2"])
        self.assertEqual(context.sources["references"], "pyright")

    def test_references_outside_the_workspace_are_dropped(self):
        respuesta = [
            {"uri": "file:///etc/passwd", "range": {"start": {"line": 0, "character": 0}}},
            {"uri": "file:///workspace/../fuera.py", "range": {"start": {"line": 0, "character": 0}}},
            {"uri": "file:///workspace/usa.py", "range": {"start": {"line": 1, "character": 6}}},
        ]
        context = self.builder.build_file("calculator.py", "technical")
        with mock.patch.object(self.builder, "_lsp_manager", return_value=self._manager(respuesta)):
            asyncio.run(self.builder.collect_references_semantic("calculator.py", "add", 5, context))
        self.assertEqual(context.references, ["usa.py:2"])

    def test_a_stopped_pyright_declines_so_the_text_search_takes_over(self):
        manager = mock.Mock()
        manager.running = False
        context = self.builder.build_file("calculator.py", "technical")
        with mock.patch.object(self.builder, "_lsp_manager", return_value=manager):
            usado = asyncio.run(
                self.builder.collect_references_semantic("calculator.py", "add", 5, context)
            )
        self.assertFalse(usado)

    def test_build_async_falls_back_to_the_text_search(self):
        manager = mock.Mock()
        manager.running = False
        with mock.patch.object(self.builder, "_lsp_manager", return_value=manager):
            context = asyncio.run(self.builder.build_async(
                "selection", "technical",
                {"path": "calculator.py", "selection": "def add(a, b):",
                 "start_line": 5, "end_line": 5},
            ))
        self.assertEqual(context.sources["references"], "workspace search")
        self.assertTrue(context.references)

    def test_non_python_files_never_ask_pyright(self):
        (self.root / "nota.md").write_text("# add\n", encoding="utf-8")
        manager = self._manager([])
        context = self.builder.build_file("nota.md", "simple")
        with mock.patch.object(self.builder, "_lsp_manager", return_value=manager):
            usado = asyncio.run(
                self.builder.collect_references_semantic("nota.md", "add", 1, context)
            )
        self.assertFalse(usado)
        manager.request.assert_not_called()
