"""Strict local API for safe workspace file and directory operations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.workspace import workspace_service
from app.core.security import require_local_origin, require_localhost
from app.core.workspace import WorkspaceError
from app.core.workspace_operations import WorkspaceOperations

router = APIRouter(
    prefix="/api/workspace/operations",
    tags=["workspace-operations"],
    dependencies=[Depends(require_localhost), Depends(require_local_origin)],
)
operations = WorkspaceOperations(workspace_service)


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    parent: str = Field(default="", max_length=4096)
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern=r"^(file|directory)$")


class DuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=120)


class MovePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=4096)
    destination_parent: str = Field(default="", max_length=4096)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class PathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=4096)


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _raise(error: WorkspaceError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    ) from None


@router.post("/create")
def create(request: CreateRequest):
    try:
        return operations.create(request.parent, request.name, request.type)
    except WorkspaceError as error:
        _raise(error)


@router.post("/duplicate")
def duplicate(request: DuplicateRequest):
    try:
        return operations.duplicate(request.source, request.name)
    except WorkspaceError as error:
        _raise(error)


@router.post("/move/preview")
def preview_move(request: MovePreviewRequest):
    try:
        return operations.preview_move(request.source, request.destination_parent, request.name)
    except WorkspaceError as error:
        _raise(error)


@router.post("/move/apply")
def apply_move(request: TokenRequest):
    try:
        return operations.apply_move(request.token)
    except WorkspaceError as error:
        _raise(error)


@router.post("/delete/preview")
def preview_delete(request: PathRequest):
    try:
        return operations.preview_delete(request.path)
    except WorkspaceError as error:
        _raise(error)


@router.post("/delete/apply")
def apply_delete(request: TokenRequest):
    try:
        return operations.apply_delete(request.token)
    except WorkspaceError as error:
        _raise(error)
