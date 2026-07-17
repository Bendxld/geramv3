"""
GitHub sign-in — GERAM CORE OS (v3, Paso 3)

Guarda de forma LOCAL y segura (permisos 0600, fuera del árbol de código, en
LOCAL_DATA_DIR) un Personal Access Token de GitHub para futuras integraciones
(Source Control, etc.). No expone el token en ninguna respuesta: solo dice si
hay sesión y, si se pudo, el login del usuario. Localhost-only; las mutaciones
exigen origen local, igual que el resto de la configuración.
"""

import json
import os
import tempfile

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, SecretStr

from app.core.config import settings
from app.core.security import require_local_origin, require_localhost

router = APIRouter(
    prefix="/api/github",
    tags=["github"],
    dependencies=[Depends(require_localhost)],
)

TOKEN_PATH = settings.LOCAL_DATA_DIR / "github_token.json"


class GithubTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: SecretStr


def _write_atomic_0600(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".github-", suffix=".tmp")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_store() -> dict:
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def _fetch_login(token: str) -> str | None:
    """Best-effort: pide el login a la API de GitHub. Si no hay red o el token
    es inválido, devuelve None (no rompe el guardado local)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
        if response.status_code == 200:
            login = response.json().get("login")
            return str(login) if login else None
    except (httpx.HTTPError, ValueError):
        return None
    return None


@router.get("/status")
async def github_status():
    """¿Hay sesión de GitHub guardada? Nunca devuelve el token."""
    store = _read_store()
    return {"connected": bool(store.get("token")), "login": store.get("login")}


@router.post("/token", dependencies=[Depends(require_local_origin)])
async def guardar_token(payload: GithubTokenRequest):
    """Guarda el token con 0600 y (best-effort) resuelve el login."""
    token = payload.token.get_secret_value().strip()
    if not token:
        raise HTTPException(status_code=422, detail={"code": "empty_token", "message": "Token is required"})
    login = await _fetch_login(token)
    try:
        _write_atomic_0600(TOKEN_PATH, json.dumps({"token": token, "login": login}) + "\n")
    except OSError as error:
        raise HTTPException(status_code=503, detail={"code": "store_failed", "message": str(error)}) from None
    return {"connected": True, "login": login}


@router.delete("/token", dependencies=[Depends(require_local_origin)])
async def cerrar_sesion():
    """Cierra sesión: borra el token guardado."""
    try:
        TOKEN_PATH.unlink(missing_ok=True)
    except OSError as error:
        raise HTTPException(status_code=503, detail={"code": "delete_failed", "message": str(error)}) from None
    return {"connected": False, "login": None}
