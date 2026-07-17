"""
/info + visibilidad del roster — GERAM CORE OS

/info da el roster de agentes incluidos (mismos que IRIS) para poblar el HUD de
A.R.E.S. Además, cada usuario puede OCULTAR/DESACTIVAR de SU vista los agentes
incluidos que no use — sin borrar código (no rompe IRIS) y de forma reversible.
La lista de ocultos se guarda como JSON en el data dir del usuario (portable).
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import require_local_origin

router = APIRouter(tags=["instance"])

_STARTED_AT = time.time()

# Roster incluido (mismos mini-empleados que expone IRIS en server.py).
BUILTIN_AGENTS = [
    "director", "balancer", "memory", "context_engine", "personality",
    "escuchar", "habla", "offline_agent", "lock_agent",
    "control_agent", "web_agent", "groq_agent", "notion_agent",
    "daily_briefing_agent", "reminder_agent", "calendar_agent", "email_agent",
    "classroom_agent", "nexus_agent", "research_agent",
    "finance_agent", "pendientes_agent",
    "screenshot_agent", "observador", "clipboard_agent", "file_organizer_agent",
    "whatsapp_agent", "adjuntos_agent", "proactividad_agent",
    "retrospectiva_agent", "telegram_agent", "obsidian_agent", "examen_agent",
]


class VisibilityRequest(BaseModel):
    id: str
    hidden: bool


def _hidden_file() -> Path:
    return settings.LOCAL_DATA_DIR / "roster_ocultos.json"


def _read_hidden() -> list[str]:
    try:
        data = json.loads(_hidden_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    # Solo devolvemos ids que sigan siendo agentes incluidos válidos.
    return sorted(a for a in data.get("hidden", []) if a in BUILTIN_AGENTS)


def _write_hidden(hidden: set[str]) -> None:
    settings.LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    valid = sorted(a for a in hidden if a in BUILTIN_AGENTS)
    _hidden_file().write_text(json.dumps({"hidden": valid}), encoding="utf-8")


@router.get("/info")
async def info():
    seconds = int(time.time() - _STARTED_AT)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return {
        # "IRIS" mantiene la identidad visual del HUD (NODO IRIS); el perfil
        # A.R.E.S. lo cambia aparte el toggle del frontend.
        "instancia": "IRIS",
        "agentes_activos": BUILTIN_AGENTS,
        "agentes_ocultos": _read_hidden(),
        "uptime": f"{hours:02d}:{minutes:02d}:{secs:02d}",
    }


@router.post("/roster/visibility", dependencies=[Depends(require_local_origin)])
async def set_visibility(body: VisibilityRequest):
    """Oculta (hidden=true) o vuelve a mostrar (false) un agente INCLUIDO. No
    borra nada: solo controla si aparece en la vista del usuario."""
    if body.id not in BUILTIN_AGENTS:
        raise HTTPException(status_code=404, detail={"code": "agent_not_found"})
    hidden = set(_read_hidden())
    if body.hidden:
        hidden.add(body.id)
    else:
        hidden.discard(body.id)
    _write_hidden(hidden)
    return {"status": "ok", "hidden": sorted(hidden)}
