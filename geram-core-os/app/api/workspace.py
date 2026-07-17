"""Localhost-only API for a bounded, existing-file text workspace."""

import subprocess

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import ROOT_DIR, settings
from app.core.security import require_local_origin, require_localhost
from app.core.workspace import MAX_FILE_BYTES, WorkspaceError, WorkspaceService


router = APIRouter(
    prefix="/api/workspace",
    tags=["workspace"],
    dependencies=[Depends(require_localhost)],
)


class WorkspaceSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=MAX_FILE_BYTES)
    base_version: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


workspace_service = WorkspaceService(
    settings.WORKSPACE_ROOT,
    protected_paths=(
        settings.LOCAL_DATA_DIR,
        settings.CREDENTIAL_STORE_PATH,
        settings.CODEX_SESSION_LOG_PATH,
        ROOT_DIR / ".env",
        ROOT_DIR / ".env.save",
    ),
)


def _raise_public(error: WorkspaceError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    ) from None


def _git_branch(root) -> str | None:
    """Rama git activa del workspace, leyendo .git/HEAD (sin subprocess).
    Devuelve None si no es un repo git."""
    try:
        head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head.startswith("ref:"):
        return head.split("/", 2)[-1] if "/" in head else head[4:].strip()
    return head[:12] if head else None  # HEAD desacoplado: hash corto


def _git_changes(root) -> int:
    """Nº de archivos con cambios (badge de Source Control, estilo VS Code).
    `git status --porcelain`, solo lectura y con timeout; 0 si no aplica."""
    if not (root / ".git").exists():
        return 0
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    if result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if line.strip())


@router.get("/status")
def get_workspace_status():
    """Estado para el HUD: nombre del workspace, rama git, nº de cambios y si
    el Modo Desarrollador de GERAM está activo (status bar, badge y banner)."""
    root = workspace_service.root
    return {
        "workspace_name": root.name,
        "developer_mode": bool(getattr(settings, "DEVELOPER_MODE", False)),
        "branch": _git_branch(root),
        "changes": _git_changes(root),
    }


@router.get("/tree")
def get_workspace_tree():
    try:
        return workspace_service.tree()
    except WorkspaceError as error:
        _raise_public(error)


@router.get("/file")
def get_workspace_file(path: str = Query(min_length=1, max_length=4096)):
    try:
        return workspace_service.read_file(path)
    except WorkspaceError as error:
        _raise_public(error)


@router.put("/file", dependencies=[Depends(require_local_origin)])
def put_workspace_file(request: WorkspaceSaveRequest):
    try:
        return workspace_service.save_file(
            request.path,
            request.content,
            request.base_version,
        )
    except WorkspaceError as error:
        _raise_public(error)
