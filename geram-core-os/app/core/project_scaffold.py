"""
Project scaffolding — GERAM CORE OS (v3, Paso 3)

Creación de proyectos "desde cero" por A.R.E.S. dentro del workspace ACTIVO,
de forma segura y acotada. Reutiliza `normalize_relative_path` de workspace.py
(que ya rechaza `..` y rutas absolutas con 403), así que ningún archivo puede
escribirse fuera del workspace. El endpoint (app/api/ares_edits.py) corre
`create_project` como tarea de fondo para no bloquear la respuesta ni el hilo
de render de Electron; este módulo solo hace E/S local, sin red ni LLM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from app.core.workspace import _public_error, normalize_relative_path

# Nombre de proyecto: un solo segmento seguro (evita rutas y caracteres raros).
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

MAX_PROJECT_FILES = 40
MAX_FILE_BYTES = 256 * 1024


def _fastapi_files(name: str) -> list[tuple[str, str]]:
    return [
        ("main.py",
         "from fastapi import FastAPI\n\n"
         f'app = FastAPI(title="{name}")\n\n\n'
         '@app.get("/")\n'
         "async def root():\n"
         '    return {"message": "Hello from ' + name + '"}\n'),
        ("requirements.txt", "fastapi\nuvicorn[standard]\n"),
        ("README.md", f"# {name}\n\nAPI FastAPI.\n\n```bash\nuvicorn main:app --reload\n```\n"),
    ]


def _flask_files(name: str) -> list[tuple[str, str]]:
    return [
        ("app.py",
         "from flask import Flask\n\n"
         "app = Flask(__name__)\n\n\n"
         '@app.route("/")\n'
         "def raiz():\n"
         f'    return "Hola desde {name}"\n\n\n'
         'if __name__ == "__main__":\n'
         "    app.run(debug=True)\n"),
        ("requirements.txt", "flask\n"),
        ("README.md", f"# {name}\n\nApp Flask.\n\n```bash\npython app.py\n```\n"),
    ]


def _python_files(name: str) -> list[tuple[str, str]]:
    return [
        ("main.py", 'def main():\n    print("Hola desde ' + name + '")\n\n\nif __name__ == "__main__":\n    main()\n'),
        ("README.md", f"# {name}\n\nProyecto Python.\n\n```bash\npython main.py\n```\n"),
    ]


def _node_files(name: str) -> list[tuple[str, str]]:
    return [
        ("index.js", f'console.log("Hola desde {name}");\n'),
        ("package.json",
         '{\n  "name": "' + name.lower() + '",\n  "version": "0.1.0",\n'
         '  "main": "index.js",\n  "scripts": {"start": "node index.js"}\n}\n'),
        ("README.md", f"# {name}\n\nProyecto Node.\n\n```bash\nnode index.js\n```\n"),
    ]


def _static_files(name: str) -> list[tuple[str, str]]:
    return [
        ("index.html",
         '<!DOCTYPE html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
         f"<title>{name}</title>\n<link rel=\"stylesheet\" href=\"style.css\">\n</head>\n"
         f"<body>\n<h1>{name}</h1>\n<script src=\"script.js\"></script>\n</body>\n</html>\n"),
        ("style.css", "body { font-family: system-ui, sans-serif; margin: 2rem; }\n"),
        ("script.js", f'console.log("Hola desde {name}");\n'),
    ]


def _generic_files(name: str) -> list[tuple[str, str]]:
    return [("README.md", f"# {name}\n\nProyecto creado por A.R.E.S.\n")]


TEMPLATES = {
    "fastapi": _fastapi_files,
    "flask": _flask_files,
    "python": _python_files,
    "node": _node_files,
    "static": _static_files,
    "generic": _generic_files,
}

# (palabras clave -> plantilla). Se evalúa en orden; la primera que aparezca gana.
_TEMPLATE_KEYWORDS = [
    ("fastapi", ("fastapi", "fast api")),
    ("flask", ("flask",)),
    ("static", ("web", "html", "static", "sitio", "página", "pagina", "landing")),
    ("node", ("node", "express", "javascript", "js ")),
    ("python", ("python", "script", "cli")),
]


def select_template(instruction: str) -> str:
    """Elige una plantilla a partir de la instrucción en lenguaje natural."""
    lowered = f" {(instruction or '').lower()} "
    for template, keywords in _TEMPLATE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return template
    return "generic"


def build_files(template: str, name: str) -> list[tuple[str, str]]:
    """Lista de (ruta_relativa, contenido) para la plantilla dada."""
    return TEMPLATES.get(template, _generic_files)(name)


def validate_project_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not _SAFE_NAME.match(cleaned):
        raise _public_error(
            "invalid_project_name",
            "The project name must be a simple safe folder name",
            422,
        )
    return cleaned


def create_project(root: Path, name: str, files: list[tuple[str, str]]) -> dict[str, object]:
    """Crea el árbol de un proyecto dentro de `root`, de forma segura.

    - `name` debe ser un nombre de carpeta simple (sin rutas ni `..`).
    - Cada ruta de archivo se valida con normalize_relative_path (rechaza `..`
      y absolutas) y se confina con realpath dentro de `root`.
    - No sobrescribe: si la carpeta del proyecto ya existe, se rechaza.
    Devuelve {"directory": name, "files": [rutas creadas]}.
    """
    project_name = validate_project_name(name)
    if not isinstance(files, list) or not files:
        raise _public_error("invalid_project_files", "No project files were provided", 422)
    if len(files) > MAX_PROJECT_FILES:
        raise _public_error("too_many_files", "The project has too many files", 413)

    resolved_root = Path(root).resolve(strict=True)
    project_dir = resolved_root / project_name
    if project_dir.exists():
        raise _public_error("project_exists", "A project with that name already exists", 409)

    created: list[str] = []
    project_dir.mkdir(parents=False)
    for relative_path, content in files:
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise _public_error("invalid_project_files", "A project file is invalid", 422)
        # Validación de traversal (comparte el guard de 403 del workspace).
        _canonical, parts = normalize_relative_path(f"{project_name}/{relative_path}")
        target = resolved_root.joinpath(*parts)
        # Defensa extra: la ruta real no puede salir de la raíz.
        real_target = os.path.realpath(target)
        if os.path.commonpath([real_target, str(resolved_root)]) != str(resolved_root):
            raise _public_error("path_escape", "The requested path is not available", 403)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 'x' = falla si existe: nunca sobrescribe archivos.
        with open(target, "x", encoding="utf-8") as stream:
            stream.write(content)
        created.append("/".join(parts))
    return {"directory": project_name, "files": created}


async def run_scaffold_background(root: Path, name: str, files: list[tuple[str, str]]) -> None:
    """Corre `create_project` en un hilo (asyncio.to_thread) sin bloquear el
    event loop ni la respuesta HTTP. Vive aquí (y no en ares_edits) porque ese
    módulo es deliberadamente libre de E/S y logging."""
    try:
        await asyncio.to_thread(create_project, root, name, files)
    except Exception:
        logging.getLogger("ares.projects").exception(
            "project scaffolding failed for %r", name
        )
