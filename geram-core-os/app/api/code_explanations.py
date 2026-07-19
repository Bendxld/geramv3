"""API de explicaciones de código de A.R.E.S. — sólo lectura.

Deliberadamente separada de ares_edits: este flujo NO crea propuestas, no
genera diffs y no tiene ruta de aplicación. Nada aquí escribe en disco, abre
un shell, lanza un proceso ni ejecuta pruebas.

Como en el resto de A.R.E.S., WorkspaceService es la única autoridad sobre
rutas y exclusiones, y se conservan las mismas guardas de origen local.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.workspace import workspace_service
from app.api.workspace_navigation import search_service
from app.core.code_explanation import (
    CodeContextBuilder,
    ExplanationError,
    build_prompt,
    offline_demo,
    response_schema,
    validate_explanation,
)
from app.core.config import settings
from app.core.providers.registry import provider_registry
from app.core.security import require_local_origin, require_localhost


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/ares/explanations",
    tags=["ares-explanations"],
    dependencies=[Depends(require_localhost)],
)

context_builder = CodeContextBuilder(workspace_service, search_service)


class EditorDiagnostic(BaseModel):
    """Un marcador que el editor ya muestra (Monaco/Pyright).

    Lo aporta el cliente porque son exactamente los que el usuario está
    viendo. Llega acotado y se trata como dato no confiable.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    severity: str = Field(default="info", max_length=20)
    line: int = Field(default=0, ge=0, le=1_000_000)
    message: str = Field(default="", max_length=500)


class ExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scope: str = Field(pattern=r"^(selection|file|project)$")
    level: str = Field(pattern=r"^(simple|technical|step_by_step|risks|architecture)$")
    path: str = Field(default="", max_length=4096)
    selection: str = Field(default="", max_length=20000)
    start_line: int = Field(default=1, ge=1, le=1_000_000)
    end_line: int = Field(default=1, ge=1, le=1_000_000)
    offline: bool = False
    diagnostics: list[EditorDiagnostic] = Field(default_factory=list, max_length=20)


def _fail(error: ExplanationError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": str(error)},
    ) from None


def _role_provider() -> tuple[str, str]:
    """Proveedor y modelo YA seleccionados para A.R.E.S. Aquí no se elige nada."""
    try:
        configured = settings.role_provider_settings("ares")
        return str(configured.provider), str(configured.model)
    except Exception:  # configuración incompleta no debe romper el preview
        return "", ""


async def _build(payload: ExplanationRequest):
    try:
        return await context_builder.build_async(
            payload.scope, payload.level, payload.model_dump()
        )
    except ExplanationError as error:
        _fail(error)


@router.post("/preview", dependencies=[Depends(require_local_origin)])
async def preview_context(payload: ExplanationRequest):
    """Lo que se enviaría al proveedor, ANTES de enviarlo. No llama al modelo."""
    context = await _build(payload)
    provider, model = _role_provider()
    return context.preview(provider, model)


@router.post("", dependencies=[Depends(require_local_origin)])
async def explain(payload: ExplanationRequest):
    context = await _build(payload)
    provider, model = _role_provider()

    if payload.offline:
        # Plantilla de demostración: nunca toca el proveedor y va marcada.
        try:
            return {
                "explanation": offline_demo(payload.scope, payload.level),
                "demo": True,
                "context": context.preview(provider, model),
            }
        except ExplanationError as error:
            _fail(error)

    prompt = build_prompt(context)
    try:
        dispatch = await provider_registry.generate_for_role(
            "ares",
            prompt,
            response_schema=response_schema(),
            response_schema_name="ares_code_explanation",
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_unavailable",
                "message": "A.R.E.S. is temporarily unavailable",
            },
        ) from None

    result = dispatch.result if isinstance(dispatch.result, dict) else {}
    raw_text = result.get("text")
    if raw_text is None:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_unavailable",
                "message": "A.R.E.S. is temporarily unavailable",
            },
        )

    # Sólo se aceptan referencias a lo que de verdad se envió.
    allowed = {item.path for item in context.files}
    if context.selection_path:
        allowed.add(context.selection_path)
    try:
        explanation = validate_explanation(
            raw_text, scope=payload.scope, level=payload.level, allowed_files=allowed
        )
    except ExplanationError as error:
        # Se registra el fallo SIN el contenido: ni código ni respuesta.
        logger.info(
            {
                "event": "ares_explanation_rejected",
                "code": error.code,
                "scope": payload.scope,
                "level": payload.level,
                "provider": dispatch.metadata.get("provider") if dispatch.metadata else None,
            }
        )
        _fail(error)

    return {
        "explanation": explanation,
        "demo": False,
        "context": context.preview(
            str((dispatch.metadata or {}).get("provider", provider)),
            str((dispatch.metadata or {}).get("model", model)),
        ),
    }
