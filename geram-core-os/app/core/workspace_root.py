"""Carpeta de trabajo elegible por el usuario, al estilo "Open Folder" de VS Code.

El workspace deja de ser un valor fijo de arranque y pasa a ser una elección
del usuario que sobrevive a los reinicios. Lo que NO cambia es la seguridad:
toda ruta candidata pasa por `validate_workspace_root`, la misma función que
valida GERAM_WORKSPACE_ROOT, así que siguen prohibidas la raíz del disco, el
home a secas, los directorios de sistema y el árbol público de `static/`.

La elección se guarda fuera del checkout (LOCAL_DATA_DIR), con los mismos
permisos 0600 y escritura atómica que el resto del estado por usuario.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from app.core.config import (
    ROOT_DIR,
    SettingsValidationError,
    developer_mode_enabled,
    settings,
    validate_workspace_root,
)


# Cota del navegador de carpetas: un directorio con miles de entradas no debe
# poder convertir un listado en una respuesta gigante ni en un escaneo eterno.
MAX_BROWSE_ENTRIES = 500


class WorkspaceRootError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _state_path() -> Path:
    return settings.LOCAL_DATA_DIR / "runtime" / "workspace-root.json"


def validate_candidate(raw_path: str) -> Path:
    """Resuelve y valida una carpeta candidata reutilizando las reglas del arranque."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise WorkspaceRootError("invalid_workspace_root", "A folder path is required")
    if "\x00" in raw_path:
        raise WorkspaceRootError("invalid_workspace_root", "The folder path is invalid")
    try:
        return validate_workspace_root(
            raw_path,
            repository_root=ROOT_DIR,
            developer_mode=developer_mode_enabled(),
            create_default=False,
        )
    except SettingsValidationError as error:
        # El validador habla en términos de la variable de entorno; aquí el
        # usuario eligió con el ratón, así que traducimos el mensaje.
        raise WorkspaceRootError(
            getattr(error, "code", "invalid_workspace_root") or "invalid_workspace_root",
            "That folder cannot be used as a workspace",
        ) from None


def load_saved() -> Path | None:
    """Carpeta guardada, o None si no hay o dejó de ser válida."""
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    stored = data.get("path")
    if not isinstance(stored, str) or not stored:
        return None
    try:
        # Se revalida en cada arranque: la carpeta pudo borrarse o moverse, y
        # las reglas de seguridad pudieron endurecerse desde que se guardó.
        return validate_candidate(stored)
    except WorkspaceRootError:
        return None


def save(path: Path) -> None:
    target = _state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=".workspace-root-", suffix=".tmp"
    )
    try:
        if hasattr(os, "fchmod"):  # Unix-only; en Windows lo maneja el perfil de usuario
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"path": str(path)}, stream)
            stream.write("\n")
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


_apply_lock = threading.RLock()


def apply(path: Path) -> Path:
    """Reapunta el workspace en caliente, sin reiniciar el proceso.

    `settings.WORKSPACE_ROOT` lo leen en tiempo de llamada el sandbox, el
    terminal watcher y el runner de tests, así que les basta con esto; el
    único que capturó la raíz al importar es `workspace_service`, y por eso
    se le reasigna explícitamente.
    """
    from app.api.workspace import workspace_service

    with _apply_lock:
        settings.WORKSPACE_ROOT = path
        workspace_service.root = path
        return path


def browse(raw_path: str | None) -> dict:
    """Lista las subcarpetas de una ruta, para el selector de carpeta.

    Es sólo de lectura y sólo devuelve directorios: nunca contenido de
    archivos. Sin argumento empieza en el home del usuario.
    """
    home = Path.home().resolve()
    if not raw_path or not str(raw_path).strip():
        current = home
    else:
        if "\x00" in str(raw_path):
            raise WorkspaceRootError("invalid_path", "The folder path is invalid")
        try:
            current = Path(str(raw_path)).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise WorkspaceRootError("folder_not_found", "That folder does not exist") from None
    if not current.is_dir():
        raise WorkspaceRootError("folder_not_found", "That folder does not exist")

    entries: list[dict] = []
    try:
        with os.scandir(current) as scanner:
            for entry in scanner:
                if len(entries) >= MAX_BROWSE_ENTRIES:
                    break
                # Ocultas fuera: el ruido de ~/.cache y compañía no ayuda a
                # elegir un proyecto, y evita exponer rutas de configuración.
                if entry.name.startswith("."):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                entries.append({"name": entry.name, "path": str(current / entry.name)})
    except PermissionError:
        raise WorkspaceRootError("folder_forbidden", "That folder cannot be read") from None
    except OSError:
        raise WorkspaceRootError("folder_not_found", "That folder does not exist") from None

    entries.sort(key=lambda item: item["name"].lower())
    parent = None if current == current.parent else str(current.parent)
    usable = True
    try:
        validate_candidate(str(current))
    except WorkspaceRootError:
        usable = False
    return {
        "path": str(current),
        "parent": parent,
        "home": str(home),
        "folders": entries,
        "usable": usable,
        "truncated": len(entries) >= MAX_BROWSE_ENTRIES,
    }
