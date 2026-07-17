"""
Orchestrator Router — GERAM CORE OS

Single entry point for every user command, regardless of origin
(local HUD, Telegram long-polling, or GCS). Responsible for routing
between the I.R.I.S. and A.R.E.S. product roles. Provider selection is
resolved independently by app/core/providers/registry.py.

procesar_orquestacion() holds the role routing logic, decoupled from
the FastAPI Request object, so non-HTTP callers (app/core/telegram_poller.py)
can reuse it without duplicating provider dispatch.
route_request() is a thin HTTP wrapper around it.
"""

import uuid

from enum import Enum
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.telemetry import get_snapshot
from app.core.gcs.skill_retriever import skill_retriever
from app.core.providers.registry import provider_registry
from app.core.user_config import system_prompt_override

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])

HEAVY_SIGNALS = (
    "code", "código", "codigo", "bug", "error", "debug", "refactor",
    "función", "funcion", "function", "script", "commit", "git",
    "test", "deploy", "repo", "archivo", "file", "python", "javascript",
)

LIGHT_SIGNALS = (
    "cpu", "ram", "estado", "status", "temperatura", "temperature",
    "hardware", "batería", "bateria", "battery", "pantalla", "screen",
    "volumen", "volume", "brillo", "brightness",
)

# Subconjunto de LIGHT_SIGNALS que específicamente pide datos de
# hardware/telemetría (no todo light signal es esto — "brillo"/"volumen"
# no ameritan un snapshot de psutil). Se usa para decidir si se inyecta
# contexto real antes de llamar a Gemini (ver _inyectar_contexto_telemetria).
HARDWARE_SIGNALS = (
    "cpu", "ram", "estado", "temperatura", "temperature",
    "memoria", "memory", "uso", "rendimiento", "performance",
)


def _con_system_prompt(prompt: str) -> str:
    """Antepone el system_prompt_override global del usuario (si existe).

    Compartido conceptualmente con A.R.E.S. (ver ares_edits._context_prompt),
    para que la personalización valga en todas las interacciones. Fail-safe:
    devuelve el prompt intacto si no hay override configurado."""
    override = system_prompt_override()
    language_instruction = (
        "[RESPONSE LANGUAGE]\nDetect the language of the user's current request "
        "and respond in that same language. Apply this to headings, status "
        "messages, explanations, and follow-up questions. If the request mixes "
        "languages, use the predominant language.\n\n"
    )
    if not override:
        return language_instruction + prompt
    return f"[USER SYSTEM PROMPT]\n{override}\n\n{language_instruction}{prompt}"


def _pide_datos_de_hardware(prompt: str) -> bool:
    prompt_lower = prompt.lower()
    return any(signal in prompt_lower for signal in HARDWARE_SIGNALS)


def _inyectar_contexto_telemetria(prompt: str) -> str:
    """Antepone un snapshot real de psutil al prompt, para que Gemini
    conteste con números reales en vez de instrucciones genéricas de
    "cómo revisar tu CPU en Windows/macOS/Linux"."""
    snapshot = get_snapshot()
    contexto = (
        "[CURRENT SYSTEM DATA]\n"
        f"CPU: {snapshot['cpu_percent']}%\n"
        f"RAM used: {snapshot['ram_percent']}% "
        f"({snapshot['ram_used_mb']} MB of {snapshot['ram_total_mb']} MB)\n\n"
        "Answer using this real data. Be direct and concise; do not explain "
        "how to check the status manually because it is already provided.\n\n"
    )
    return contexto + prompt


def classify_mode(prompt: str, source: str, force_mode: str | None) -> str:
    """Decides 'iris' vs 'ares'. Manual override and GCS source win outright."""
    if force_mode:
        return force_mode

    if source == "gcs":
        return "ares"

    prompt_lower = prompt.lower()

    if any(signal in prompt_lower for signal in HEAVY_SIGNALS):
        return "ares"

    if any(signal in prompt_lower for signal in LIGHT_SIGNALS):
        return "iris"

    return "iris"


class SourceChannel(str, Enum):
    HUD_LOCAL = "hud_local"
    TELEGRAM = "telegram"
    GCS = "gcs"


class OrchestratorRequest(BaseModel):
    prompt: str
    source: SourceChannel
    force_mode: str | None = None  # manual override: "iris" | "ares"
    # Offline-first: when True, a confident local Skill match answers WITHOUT
    # calling any external provider. Default False preserves provider dispatch.
    prefer_local_skills: bool = False


class OrchestratorResponse(BaseModel):
    mode: str
    session_id: str
    result: dict
    metadata: dict


async def procesar_orquestacion(
    prompt: str,
    source: str,
    force_mode: str | None = None,
    session_id: str | None = None,
    prefer_local_skills: bool = False,
) -> OrchestratorResponse:
    """Lógica real de ruteo, sin nada de FastAPI/Request de por medio —
    la usan tanto route_request() (HTTP) como el poller de Telegram."""
    session_id = session_id or str(uuid.uuid4())
    mode = classify_mode(prompt, source, force_mode)

    # Offline-first Skill Retriever short-circuit: if a local Skill confidently
    # covers the prompt, answer from local knowledge and skip the provider
    # entirely (works with zero API keys). Opt-in so provider dispatch stays
    # the default for normal chat.
    if prefer_local_skills:
        retrieval = skill_retriever.retrieve(prompt, profile=mode)
        if retrieval.handled_locally and retrieval.best is not None:
            skill = retrieval.best.skill
            return OrchestratorResponse(
                mode=mode,
                session_id=session_id,
                result={"text": skill.body, "skill": skill.summary()},
                metadata={
                    "source": source,
                    "provider": "local",
                    "handled_locally": True,
                    "skill_used": skill.id,
                    "fallback_used": False,
                },
            )

    provider_prompt = prompt
    if mode == "iris" and _pide_datos_de_hardware(prompt):
        provider_prompt = _inyectar_contexto_telemetria(prompt)

    # Inyección del system prompt global del usuario (v3, Paso 2): si hay un
    # system_prompt_override en .geram-config.json, se antepone como base a
    # TODA interacción (IRIS y A.R.E.S. comparten este prefijo). Fail-safe:
    # si no hay config o está vacío, no cambia nada.
    provider_prompt = _con_system_prompt(provider_prompt)

    dispatch = await provider_registry.generate_for_role(mode, provider_prompt)

    return OrchestratorResponse(
        mode=mode,
        session_id=session_id,
        result=dispatch.result,
        metadata={"source": source, **dispatch.metadata},
    )


@router.post("/route", response_model=OrchestratorResponse)
async def route_request(payload: OrchestratorRequest, request: Request):
    """Central routing endpoint. Decide IRIS vs ARES y despacha la tarea."""
    session_id = getattr(request.state, "session_id", "unknown")
    return await procesar_orquestacion(
        payload.prompt,
        payload.source.value,
        payload.force_mode,
        session_id,
        prefer_local_skills=payload.prefer_local_skills,
    )
