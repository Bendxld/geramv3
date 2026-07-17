"""Testing UI API backed exclusively by the existing closed test runners."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.api.workspace import workspace_service
from app.core.security import require_local_origin, require_localhost
from app.core.test_discovery import UnittestDiscovery
from app.core.test_runner import TestRunSpec, start_test

router = APIRouter(prefix="/api/testing", tags=["testing"], dependencies=[Depends(require_localhost)])
discovery = UnittestDiscovery(workspace_service)

_PUBLIC_START_FIELDS = {
    "run_id", "status", "runner", "target", "selector", "sandbox_backend",
    "cleanup_status", "error",
}
_PUBLIC_ERRORS = {
    "runner_not_allowed", "target_not_allowed", "invalid_test_target",
    "invalid_test_selector", "invalid_timeout", "sandbox_unavailable",
    "node_unavailable", "run_capacity", "testing_runner_error",
}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    runner: Literal["node_script", "python_file", "python_unittest"]
    target: str = Field(min_length=1, max_length=4096)
    selector: str = Field(default="", max_length=260)
    timeout_seconds: float = Field(default=30.0, gt=0, le=60.0)


@router.get("/discovery")
def discover():
    return discovery.discover()


@router.post("/runs", dependencies=[Depends(require_local_origin)])
async def start(request: RunRequest):
    try:
        result = start_test(TestRunSpec(request.runner, request.target, request.timeout_seconds, request.selector))
    except Exception:
        result = {"status": "unavailable", "error": "testing_runner_error", "cleanup_status": "not_started"}
    public = {key: value for key, value in result.items() if key in _PUBLIC_START_FIELDS}
    if public.get("error") not in _PUBLIC_ERRORS:
        public["error"] = "testing_runner_error"
    return public
