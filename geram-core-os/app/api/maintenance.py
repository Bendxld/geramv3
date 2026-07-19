"""Local maintenance API: diagnostics, portable backups, and recovery."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal

from app.core.maintenance import (
    MaintenanceError,
    create_backup,
    diagnostics,
    list_backups,
    restore_backup,
)
from app.core.security import require_local_origin, require_localhost


router = APIRouter(
    prefix="/api/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_localhost)],
)


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    backup_id: str
    confirm: Literal["RESTORE"]


@router.get("/diagnostics")
async def get_diagnostics():
    return diagnostics()


@router.get("/backups")
async def get_backups():
    return {"backups": list_backups()}


@router.post("/backups", dependencies=[Depends(require_local_origin)])
async def make_backup():
    try:
        return {"status": "ok", "backup": create_backup()}
    except (MaintenanceError, OSError) as error:
        code = error.code if isinstance(error, MaintenanceError) else "backup_failed"
        raise HTTPException(status_code=503, detail={"code": code, "message": str(error)}) from None


@router.post("/restore", dependencies=[Depends(require_local_origin)])
async def restore(payload: RestoreRequest):
    try:
        return restore_backup(payload.backup_id)
    except MaintenanceError as error:
        status = 404 if error.code == "backup_not_found" else 422
        raise HTTPException(status_code=status, detail={"code": error.code, "message": str(error)}) from None
    except OSError:
        raise HTTPException(status_code=503, detail={"code": "restore_failed", "message": "Restore failed"}) from None
