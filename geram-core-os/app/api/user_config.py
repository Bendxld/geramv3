"""
User Config Router — GERAM CORE OS (v3, Paso 2)

Local profile / identity / privacy settings persisted in the per-user GERAM
data directory. A legacy project-root `.geram-config.json` is migrated once.
Separate from the /config router (which manages the .env provider secrets):

    GET  /api/config   -> current config (auto-created with defaults if absent)
    POST /api/config   -> validate (Pydantic) and persist with 0600 perms

Both are localhost-only; writes additionally require a local origin, matching
the existing settings endpoints.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import require_local_origin, require_localhost
from app.core.user_config import (
    CONFIG_PATH,
    GeramConfig,
    load_config,
    save_config,
)


class ManualSeenUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(ge=1, le=10000)


class SetupCompleteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(ge=1, le=10000)

router = APIRouter(
    prefix="/api/config",
    tags=["user-config"],
    dependencies=[Depends(require_localhost)],
)


@router.get("")
async def obtener_config():
    """Return the local config, generating defaults on first access."""
    try:
        config = load_config(CONFIG_PATH, create_if_missing=True)
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_config_file", "message": str(error)},
        ) from None
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "config_unavailable", "message": str(error)},
        ) from None
    return config.model_dump(mode="json")


@router.post("", dependencies=[Depends(require_local_origin)])
async def actualizar_config(payload: GeramConfig):
    """Replace the whole config with a strictly-validated document."""
    try:
        saved = save_config(payload, CONFIG_PATH)
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "config_write_failed", "message": str(error)},
        ) from None
    return {"status": "ok", "config": saved.model_dump(mode="json")}


@router.post("/manual-seen", dependencies=[Depends(require_local_origin)])
async def marcar_manual_visto(payload: ManualSeenUpdate):
    """Persist only onboarding progress without overwriting other preferences."""
    try:
        config = load_config(CONFIG_PATH, create_if_missing=True)
        config.onboarding.manual_version_seen = max(
            config.onboarding.manual_version_seen,
            payload.version,
        )
        saved = save_config(config, CONFIG_PATH)
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_config_file", "message": str(error)},
        ) from None
    except OSError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "config_write_failed", "message": str(error)},
        ) from None
    return {
        "status": "ok",
        "manual_version_seen": saved.onboarding.manual_version_seen,
    }


@router.post("/setup-complete", dependencies=[Depends(require_local_origin)])
async def completar_configuracion(payload: SetupCompleteUpdate):
    """Persist first-run completion without overwriting later preferences."""
    try:
        config = load_config(CONFIG_PATH, create_if_missing=True)
        config.onboarding.setup_version_seen = max(
            config.onboarding.setup_version_seen,
            payload.version,
        )
        saved = save_config(config, CONFIG_PATH)
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_config_file", "message": str(error)},
        ) from None
    except OSError:
        raise HTTPException(
            status_code=503,
            detail={"code": "config_write_failed", "message": "Setup state could not be saved"},
        ) from None
    return {
        "status": "ok",
        "setup_version_seen": saved.onboarding.setup_version_seen,
    }
