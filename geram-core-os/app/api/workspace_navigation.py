"""Loopback-only project navigation, search, and replacement API."""
from __future__ import annotations

import asyncio
import secrets
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.workspace import workspace_service
from app.core.security import require_local_origin, require_localhost
from app.core.workspace import WorkspaceError
from app.core.workspace_search import MAX_RESULTS, SearchError, SearchOptions, WorkspaceSearchService

router = APIRouter(prefix="/api/navigation", tags=["navigation"], dependencies=[Depends(require_localhost)])
search_service = WorkspaceSearchService(workspace_service)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_JOB_TTL = 120


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=256)
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = False
    include: list[str] = Field(default_factory=list, max_length=16)
    exclude: list[str] = Field(default_factory=list, max_length=16)
    limit: int = Field(default=200, ge=1, le=MAX_RESULTS)

    def options(self) -> SearchOptions:
        return SearchOptions(
            query=self.query, regex=self.regex, case_sensitive=self.case_sensitive,
            whole_word=self.whole_word, include=tuple(self.include), exclude=tuple(self.exclude), limit=self.limit,
        )


class ReplacePreviewRequest(SearchRequest):
    replacement: str = Field(max_length=262144)


class ReplaceApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _raise(error: SearchError | WorkspaceError) -> None:
    status = error.status_code
    raise HTTPException(status_code=status, detail={"code": error.code, "message": str(error)}) from None


@router.get("/files")
def files():
    try:
        return search_service.files()
    except WorkspaceError as error:
        _raise(error)


@router.post("/search", dependencies=[Depends(require_local_origin)])
async def search(request: SearchRequest):
    cancel = threading.Event()
    try:
        return await asyncio.to_thread(search_service.search, request.options(), cancel)
    except asyncio.CancelledError:
        cancel.set()
        raise
    except (SearchError, WorkspaceError) as error:
        _raise(error)


def _expire_jobs() -> None:
    now = time.monotonic()
    for job_id, job in tuple(_jobs.items()):
        if now - job["created"] > _JOB_TTL:
            job["cancel"].set()
            _jobs.pop(job_id, None)


def _run_job(job_id: str, options: SearchOptions) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return
    try:
        result = search_service.search(options, job["cancel"])
        with _jobs_lock:
            if job_id in _jobs and _jobs[job_id]["status"] != "cancelled":
                _jobs[job_id].update(status="complete", result=result)
    except SearchError as error:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update(status="cancelled" if error.code == "search_cancelled" else "error", error=error.code)
    except Exception:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update(status="error", error="search_failed")


@router.post("/search/jobs", status_code=202, dependencies=[Depends(require_local_origin)])
async def start_search_job(request: SearchRequest):
    job_id = secrets.token_urlsafe(24)
    with _jobs_lock:
        _expire_jobs()
        _jobs[job_id] = {"created": time.monotonic(), "status": "searching", "cancel": threading.Event()}
    worker = threading.Thread(target=_run_job, args=(job_id, request.options()), name="geram-workspace-search", daemon=True)
    with _jobs_lock:
        _jobs[job_id]["worker"] = worker
    worker.start()
    return {"job_id": job_id, "status": "searching"}


@router.get("/search/jobs/{job_id}")
def get_search_job(job_id: str):
    if not re_full_job_id(job_id):
        raise HTTPException(status_code=404, detail={"code": "search_job_not_found"})
    with _jobs_lock:
        _expire_jobs()
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "search_job_not_found"})
        response = {"status": job["status"]}
        if "result" in job:
            response["result"] = job["result"]
        if "error" in job:
            response["error"] = job["error"]
        return response


def re_full_job_id(value: str) -> bool:
    return isinstance(value, str) and 24 <= len(value) <= 64 and all(character.isalnum() or character in "-_" for character in value)


@router.delete("/search/jobs/{job_id}", dependencies=[Depends(require_local_origin)])
def cancel_search_job(job_id: str):
    if not re_full_job_id(job_id):
        raise HTTPException(status_code=404, detail={"code": "search_job_not_found"})
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail={"code": "search_job_not_found"})
        job["cancel"].set()
        job["status"] = "cancelled"
    return {"status": "cancelled"}


def stop_search_jobs() -> None:
    with _jobs_lock:
        jobs = list(_jobs.values())
        for job in jobs:
            job["cancel"].set()
    for job in jobs:
        worker = job.get("worker")
        if worker and worker.is_alive():
            worker.join(timeout=1.0)
    with _jobs_lock:
        _jobs.clear()


@router.post("/replacements/preview", dependencies=[Depends(require_local_origin)])
async def preview_replace(request: ReplacePreviewRequest):
    try:
        return await asyncio.to_thread(search_service.preview_replace, request.options(), request.replacement)
    except (SearchError, WorkspaceError) as error:
        _raise(error)


@router.post("/replacements/apply", dependencies=[Depends(require_local_origin)])
async def apply_replace(request: ReplaceApplyRequest):
    try:
        return await asyncio.to_thread(search_service.apply_replace, request.token)
    except (SearchError, WorkspaceError) as error:
        _raise(error)
