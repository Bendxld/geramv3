"""Tests para la creación asíncrona de proyectos por A.R.E.S. (v3, Paso 3):
andamiaje acotado al workspace, rechazo de traversal, y el endpoint que
responde 202 SIN bloquear (la escritura corre en un hilo de fondo, para no
congelar el hilo de render de Electron)."""

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api import ares_edits
from app.api.ares_edits import AresProjectRequest, crear_proyecto
from app.core import project_scaffold as ps
from app.core.workspace import WorkspaceError


class ProjectScaffoldCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_creates_bounded_project_tree(self):
        result = ps.create_project(self.root, "miapi", ps.build_files("fastapi", "miapi"))
        self.assertEqual(result["directory"], "miapi")
        self.assertTrue((self.root / "miapi" / "main.py").is_file())
        self.assertTrue((self.root / "miapi" / "requirements.txt").is_file())

    def test_directory_traversal_in_file_path_is_403(self):
        with self.assertRaises(WorkspaceError) as raised:
            ps.create_project(self.root, "evil", [("../escape.py", "x = 1\n")])
        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse((self.root.parent / "escape.py").exists())

    def test_absolute_looking_file_path_is_contained_not_escaped(self):
        # Una ruta de archivo con pinta de absoluta se CONTIENE dentro del
        # proyecto (evil/etc/passwd), nunca escribe en el /etc real.
        ps.create_project(self.root, "evil", [("/etc/passwd", "x")])
        self.assertFalse(Path("/etc/passwd_geram_test").exists())
        self.assertTrue((self.root / "evil" / "etc" / "passwd").is_file())

    def test_unsafe_project_name_is_422(self):
        for bad in ("../etc", "a/b", "/abs", "with space"):
            with self.subTest(name=bad):
                with self.assertRaises(WorkspaceError) as raised:
                    ps.create_project(self.root, bad, [("a.py", "x")])
                self.assertEqual(raised.exception.status_code, 422)

    def test_existing_project_is_409_and_never_overwrites(self):
        ps.create_project(self.root, "p", [("a.py", "original\n")])
        with self.assertRaises(WorkspaceError) as raised:
            ps.create_project(self.root, "p", [("a.py", "hacked\n")])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual((self.root / "p" / "a.py").read_text(encoding="utf-8"), "original\n")

    def test_template_selection_from_instruction(self):
        self.assertEqual(ps.select_template("crea una API con FastAPI"), "fastapi")
        self.assertEqual(ps.select_template("hazme un sitio web"), "static")
        self.assertEqual(ps.select_template("una app Flask"), "flask")
        self.assertEqual(ps.select_template("un script en python"), "python")
        self.assertEqual(ps.select_template("algo indefinido"), "generic")


class ProjectEndpointAsyncTests(unittest.TestCase):
    def test_endpoint_returns_202_without_blocking_then_scaffolds(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                release = threading.Event()
                real_create = ps.create_project

                def slow_create(target_root, name, files):
                    # Simula E/S lenta: si el endpoint fuera bloqueante, la
                    # respuesta no volvería hasta liberar este evento.
                    release.wait(3)
                    return real_create(target_root, name, files)

                with patch.object(ares_edits.workspace_service, "root", root), \
                        patch.object(ps, "create_project", slow_create):
                    response = await crear_proyecto(
                        AresProjectRequest(name="proj", instruction="crea una API FastAPI")
                    )
                    # 1) Responde de inmediato con estado "scaffolding".
                    self.assertEqual(response["status"], "scaffolding")
                    self.assertEqual(response["directory"], "proj")
                    self.assertEqual(response["template"], "fastapi")
                    # 2) NO bloqueó: el proyecto aún no existe (create_project
                    #    sigue esperando en el hilo de fondo).
                    self.assertFalse((root / "proj").exists())
                    # 3) Liberamos y dejamos terminar la tarea de fondo.
                    release.set()
                    for _ in range(50):
                        if (root / "proj" / "main.py").is_file():
                            break
                        await asyncio.sleep(0.05)
                self.assertTrue((root / "proj" / "main.py").is_file())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
