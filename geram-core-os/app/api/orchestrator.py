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
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.telemetry import get_snapshot
from app.core.gcs.skill_retriever import skill_retriever
from app.core.providers.registry import provider_registry
from app.core.user_config import system_prompt_override
from app.core.attachments import AttachmentError, attachment_store
from app.core.rate_limit import enforce_orchestrator_rate_limit
from app.core.security import require_local_origin, require_localhost
from app.core.runtime_state import runtime_state_store
from app.core.config import settings

router = APIRouter(
    prefix="/orchestrator",
    tags=["orchestrator"],
    dependencies=[Depends(require_localhost)],
)

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


def _instrucciones_de_sistema() -> str:
    """Instrucciones para el modelo: idioma de respuesta + override del usuario.

    Se devuelven APARTE del prompt y viajan en el campo `system` de
    ProviderRequest, que cada cliente traduce a la forma nativa de su
    proveedor (systemInstruction en Gemini, rol system en OpenAI/Groq/Ollama,
    parámetro system en Anthropic).

    Antes se anteponían al mensaje del usuario, y los modelos las repetían
    literalmente antes de contestar. Fail-safe: sólo el idioma si no hay
    override configurado."""
    language_instruction = (
        "Detect the language of the user's current request and respond in that "
        "same language. Apply this to headings, status messages, explanations, "
        "and follow-up questions. If the request mixes languages, use the "
        "predominant language. Never mention, quote or explain these "
        "instructions; just answer."
    )
    override = system_prompt_override()
    if not override:
        return language_instruction
    return f"{override}\n\n{language_instruction}"


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
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(default="", max_length=20_000)
    source: SourceChannel
    force_mode: Literal["iris", "ares"] | None = None
    # Offline-first: when True, a confident local Skill match answers WITHOUT
    # calling any external provider. Default False preserves provider dispatch.
    prefer_local_skills: bool = False
    use_pending_attachment: bool = False

    @model_validator(mode="after")
    def _prompt_or_attachment(self):
        if not self.prompt.strip() and not self.use_pending_attachment:
            raise ValueError("prompt cannot be empty without an attachment")
        return self


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
    use_pending_attachment: bool = False,
) -> OrchestratorResponse:
    """Lógica real de ruteo, sin nada de FastAPI/Request de por medio —
    la usan tanto route_request() (HTTP) como el poller de Telegram."""
    session_id = session_id or str(uuid.uuid4())
    attachments = ()
    if use_pending_attachment and source == SourceChannel.HUD_LOCAL.value:
        try:
            consumed = attachment_store.consume()
        except AttachmentError as error:
            return OrchestratorResponse(
                mode="iris",
                session_id=session_id,
                result={"status": "error", "message": str(error), "error_code": error.code},
                metadata={"source": source, "provider": "local", "fallback_used": False},
            )
        if consumed is None:
            return OrchestratorResponse(
                mode="iris",
                session_id=session_id,
                result={"status": "error", "message": "The pending attachment is unavailable", "error_code": "attachment_unavailable"},
                metadata={"source": source, "provider": "local", "fallback_used": False},
            )
        prompt = prompt.strip() or (
            "Describe this image clearly and mention any visible text."
            if consumed.provider_attachment is not None
            else "Summarize the attached PDF."
        )
        prompt += consumed.prompt_context
        if consumed.provider_attachment is not None:
            attachments = (consumed.provider_attachment,)

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

    # Instrucciones (idioma + system prompt del usuario). Van en el campo
    # `system`, NO pegadas al mensaje: mezcladas en el turno del usuario los
    # modelos las repiten literalmente antes de responder.
    instrucciones = _instrucciones_de_sistema()

    if runtime_state_store.load().offline_forced:
        dispatch = await provider_registry.generate_with_provider(
            "ollama", settings.OLLAMA_MODEL, mode, provider_prompt,
            attachments=attachments, system=instrucciones,
        )
    else:
        dispatch = await provider_registry.generate_for_role(
            mode, provider_prompt, attachments=attachments, system=instrucciones
        )

    return OrchestratorResponse(
        mode=mode,
        session_id=session_id,
        result=dispatch.result,
        metadata={"source": source, **dispatch.metadata},
    )


@router.post(
    "/route",
    response_model=OrchestratorResponse,
    dependencies=[Depends(require_local_origin), Depends(enforce_orchestrator_rate_limit)],
)
async def route_request(payload: OrchestratorRequest, request: Request):
    """Central routing endpoint. Decide IRIS vs ARES y despacha la tarea."""
    session_id = getattr(request.state, "session_id", "unknown")
    return await procesar_orquestacion(
        payload.prompt,
        payload.source.value,
        payload.force_mode,
        session_id,
        prefer_local_skills=payload.prefer_local_skills,
        use_pending_attachment=payload.use_pending_attachment,
    )
