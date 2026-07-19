"""Real, local, per-user runtime state plus bounded media inputs."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sqlite3
import sys

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from app.core.agent_roster import agent_roster_store
from app.core.attachments import MAX_ATTACHMENT_BYTES, AttachmentError, attachment_store
from app.core.config import settings
from app.core.credential_pool import CredentialPoolError, credential_pool_manager
from app.core.gcs.integrations import integration_hub
from app.core.providers.base import ProviderAttachment
from app.core.providers.registry import provider_registry
from app.core.runtime_state import runtime_state_store
from app.core.security import require_local_origin, require_localhost
from app.core.user_config import load_config_safe
from app.core.sandbox_backend import SandboxUnavailableError, detect_sandbox_backend


router = APIRouter(
    prefix="/api/runtime",
    tags=["runtime"],
    dependencies=[Depends(require_localhost)],
)
media_router = APIRouter(
    prefix="/api/media",
    tags=["media"],
    dependencies=[Depends(require_localhost)],
)


class RuntimePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    voice_enabled: bool | None = None
    vision_enabled: bool | None = None
    offline_forced: bool | None = None


async def _ollama_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=0.4, follow_redirects=False) as client:
            response = await client.get("http://127.0.0.1:11434/api/tags")
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _provider_configured(provider_id: str) -> bool:
    if provider_id == "ollama":
        return True
    try:
        if credential_pool_manager.has_credentials(provider_id):
            return True
    except (CredentialPoolError, sqlite3.Error, OSError):
        # El pool puede fallar de forma transitoria; la clave del entorno sigue
        # siendo válida, así que se cae al fallback en lugar de reportar
        # "no configurado" por un error de almacenamiento.
        pass
    return bool(settings.provider_api_key(provider_id))


def _platform_status() -> dict[str, object]:
    release = platform.release().lower()
    is_wsl = bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in release
    try:
        sandbox = detect_sandbox_backend().name
    except SandboxUnavailableError:
        sandbox = "unavailable"
    return {
        "os": "windows" if sys.platform == "win32" else ("macos" if sys.platform == "darwin" else "linux"),
        "deployment": "wsl2" if is_wsl else "native",
        "wsl_distro": os.environ.get("WSL_DISTRO_NAME", "")[:80] if is_wsl else "",
        "dependencies": {
            "sandbox": sandbox == "bubblewrap",
            "git": shutil.which("git") is not None,
            "node": shutil.which("node") is not None,
            "python": shutil.which("python3") is not None or shutil.which("python") is not None,
            "pdf_text": shutil.which("pdftotext") is not None,
        },
    }


@router.get("/state")
async def get_runtime_state():
    return runtime_state_store.load().model_dump(mode="json")


@router.patch("/state", dependencies=[Depends(require_local_origin)])
async def patch_runtime_state(payload: RuntimePatch):
    changes = {
        key: value
        for key, value in payload.model_dump(exclude_none=True).items()
    }
    if not changes:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_runtime_update", "message": "No state change was supplied"},
        )
    try:
        updated = runtime_state_store.update(changes)
    except OSError:
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_state_unavailable", "message": "Runtime state could not be saved"},
        ) from None
    return updated.model_dump(mode="json")


@router.get("/status")
async def runtime_status():
    roster = agent_roster_store.list_all()
    ollama_available = await _ollama_available()
    roles = {}
    for role in ("iris", "ares"):
        configured = settings.role_provider_settings(role)
        provider_configured = _provider_configured(configured.provider)
        if configured.provider == "ollama":
            provider_configured = provider_configured and ollama_available
        roles[role] = {
            "provider": configured.provider,
            "model": configured.model,
            "configured": provider_configured,
        }
    integrations = integration_hub.list_integrations()
    profile = load_config_safe().user_profile
    return {
        "status": "online",
        "local_first": True,
        "platform": _platform_status(),
        "user": {"name": profile.name.strip() or "Local user"},
        "roles": roles,
        "ollama_available": ollama_available,
        "integrations": integrations,
        "agents": {
            "total": len(roster),
            "enabled": sum(bool(agent["enabled"]) for agent in roster),
            "loaded": sum(bool(agent["loaded"]) for agent in roster),
        },
        "media": {
            "pdf_text": shutil.which("pdftotext") is not None,
            "local_whisper": importlib.util.find_spec("faster_whisper") is not None,
            "provider_audio": bool(roles["iris"]["configured"]) and "audio" in provider_registry.get(
                roles["iris"]["provider"]
            ).spec.input_modalities,
            "browser_tts": True,
        },
        "state": runtime_state_store.load().model_dump(mode="json"),
    }


async def _bounded_body(request: Request, limit: int = MAX_ATTACHMENT_BYTES) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise HTTPException(status_code=413, detail={"code": "media_too_large"})
        except ValueError:
            raise HTTPException(status_code=400, detail={"code": "invalid_content_length"}) from None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail={"code": "media_too_large"})
        chunks.append(chunk)
    return b"".join(chunks)


@media_router.post("/attachments", dependencies=[Depends(require_local_origin)])
async def save_attachment(
    request: Request,
    filename: str = Query(default="attachment", min_length=1, max_length=240),
):
    data = await _bounded_body(request)
    try:
        return attachment_store.save(filename, data)
    except AttachmentError as error:
        status = 413 if error.code == "attachment_too_large" else 422
        raise HTTPException(
            status_code=status,
            detail={"code": error.code, "message": str(error)},
        ) from None
    except OSError:
        raise HTTPException(
            status_code=503,
            detail={"code": "attachment_store_unavailable", "message": "The attachment could not be stored"},
        ) from None


@media_router.delete("/attachments", dependencies=[Depends(require_local_origin)])
async def discard_attachment():
    attachment_store.discard()
    return {"status": "discarded"}


def _audio_type(data: bytes, content_type: str) -> str:
    declared = content_type.split(";", 1)[0].strip().lower()
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "audio/webm"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "audio/mp4"
    if declared in {"audio/webm", "audio/wav", "audio/ogg", "audio/mp4", "audio/mpeg"}:
        return declared
    raise HTTPException(
        status_code=422,
        detail={"code": "unsupported_audio", "message": "Unsupported audio format"},
    )


@media_router.post("/audio", dependencies=[Depends(require_local_origin)])
async def transcribe_audio(request: Request):
    data = await _bounded_body(request)
    if not data:
        raise HTTPException(status_code=422, detail={"code": "empty_audio"})
    media_type = _audio_type(data, request.headers.get("content-type", ""))
    dispatch = await provider_registry.generate_for_role(
        "iris",
        "Transcribe this audio exactly. Return only the spoken text, preserving the language used.",
        attachments=(ProviderAttachment(media_type=media_type, data=data, filename="recording"),),
    )
    text = dispatch.result.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(
            status_code=503,
            detail={
                "code": str(dispatch.result.get("error_code", "transcription_unavailable")),
                "message": str(dispatch.result.get("message", "Audio transcription is unavailable")),
            },
        )
    return {"texto": text.strip(), "engine": dispatch.metadata.get("provider", "")}
