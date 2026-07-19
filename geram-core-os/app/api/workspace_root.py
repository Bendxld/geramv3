"""Endpoints de "Abrir carpeta": navegar el disco y elegir el workspace."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.core import workspace_root as workspace_root_store
from app.core.config import settings
from app.core.security import require_local_origin, require_localhost


router = APIRouter(
    prefix="/api/workspace/root",
    tags=["workspace"],
    dependencies=[Depends(require_localhost)],
)


class OpenFolderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=4096)


def _fail(error: workspace_root_store.WorkspaceRootError) -> None:
    # 404 cuando la carpeta no está; 422 cuando está pero no sirve como
    # workspace (demasiado amplia, dentro del árbol público, etc.).
    status = 404 if error.code == "folder_not_found" else 422
    raise HTTPException(
        status_code=status,
        detail={"code": error.code, "message": str(error)},
    ) from None


@router.get("")
async def current_root():
    return {"path": str(settings.WORKSPACE_ROOT)}


@router.get("/browse")
async def browse(path: str | None = Query(default=None, max_length=4096)):
    try:
        return workspace_root_store.browse(path)
    except workspace_root_store.WorkspaceRootError as error:
        _fail(error)


@router.post("", dependencies=[Depends(require_local_origin)])
async def open_folder(payload: OpenFolderRequest):
    try:
        resolved = workspace_root_store.validate_candidate(payload.path)
    except workspace_root_store.WorkspaceRootError as error:
        _fail(error)
    try:
        workspace_root_store.save(resolved)
    except OSError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workspace_root_unavailable",
                "message": "The folder choice could not be saved",
            },
        ) from None
    workspace_root_store.apply(resolved)
    return {"path": str(resolved)}
