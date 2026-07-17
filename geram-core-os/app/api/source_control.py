"""Strict localhost API for the closed local Git service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.workspace import workspace_service
from app.core.git_service import GitService
from app.core.security import require_local_origin, require_localhost
from app.core.workspace import WorkspaceError

router = APIRouter(
    prefix="/api/source-control", tags=["source-control"],
    dependencies=[Depends(require_localhost)],
)
service = GitService(workspace_service)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PathsRequest(StrictModel):
    project: str = Field(default="", max_length=4096)
    paths: list[str] = Field(min_length=1, max_length=100)


class CommitPreviewRequest(StrictModel):
    project: str = Field(default="", max_length=4096)
    message: str = Field(min_length=1, max_length=200)


class BranchRequest(StrictModel):
    project: str = Field(default="", max_length=4096)
    branch: str = Field(min_length=1, max_length=120)
    create: bool = False


class DiscardPreviewRequest(StrictModel):
    project: str = Field(default="", max_length=4096)
    path: str = Field(min_length=1, max_length=4096)


class TokenRequest(StrictModel):
    token: str = Field(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _raise(error: WorkspaceError) -> None:
    raise HTTPException(error.status_code, detail={"code": error.code, "message": str(error)}) from None


@router.get("/status")
def status(project: str = Query(default="", max_length=4096)):
    try: return service.status(project)
    except WorkspaceError as error: _raise(error)


@router.get("/diff")
def diff(path: str = Query(min_length=1, max_length=4096), project: str = Query(default="", max_length=4096), staged: bool = False):
    try: return service.diff(project, path, staged)
    except WorkspaceError as error: _raise(error)


@router.post("/stage", dependencies=[Depends(require_local_origin)])
def stage(request: PathsRequest):
    try: return service.stage(request.project, request.paths)
    except WorkspaceError as error: _raise(error)


@router.post("/unstage", dependencies=[Depends(require_local_origin)])
def unstage(request: PathsRequest):
    try: return service.unstage(request.project, request.paths)
    except WorkspaceError as error: _raise(error)


@router.post("/commit/preview", dependencies=[Depends(require_local_origin)])
def preview_commit(request: CommitPreviewRequest):
    try: return service.preview_commit(request.project, request.message)
    except WorkspaceError as error: _raise(error)


@router.post("/commit/apply", dependencies=[Depends(require_local_origin)])
def apply_commit(request: TokenRequest):
    try: return service.apply_commit(request.token)
    except WorkspaceError as error: _raise(error)


@router.get("/branches")
def branches(project: str = Query(default="", max_length=4096)):
    try: return service.branches(project)
    except WorkspaceError as error: _raise(error)


@router.post("/switch", dependencies=[Depends(require_local_origin)])
def switch(request: BranchRequest):
    try: return service.switch(request.project, request.branch, create=request.create)
    except WorkspaceError as error: _raise(error)


@router.post("/discard/preview", dependencies=[Depends(require_local_origin)])
def preview_discard(request: DiscardPreviewRequest):
    try: return service.preview_discard(request.project, request.path)
    except WorkspaceError as error: _raise(error)


@router.post("/discard/apply", dependencies=[Depends(require_local_origin)])
def apply_discard(request: TokenRequest):
    try: return service.apply_discard(request.token)
    except WorkspaceError as error: _raise(error)
