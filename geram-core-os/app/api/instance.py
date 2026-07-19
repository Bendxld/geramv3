"""
/info + visibilidad del roster — GERAM CORE OS

/info y /api/agents/roster usan el mismo descubrimiento seguro. La preferencia
habilitado/deshabilitado se guarda por usuario sin borrar ni importar módulos.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.agent_roster import AgentRosterError, agent_roster_store
from app.core.security import require_local_origin, require_localhost

router = APIRouter(tags=["instance"], dependencies=[Depends(require_localhost)])

_STARTED_AT = time.time()

class VisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    hidden: bool


class RosterStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool


@router.get("/info")
async def info():
    seconds = int(time.time() - _STARTED_AT)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return {
        # "IRIS" mantiene la identidad visual del HUD (NODO IRIS); el perfil
        # A.R.E.S. lo cambia aparte el toggle del frontend.
        "instancia": "IRIS",
        "agentes_activos": agent_roster_store.list_all(),
        "agentes_ocultos": [
            agent["nombre"]
            for agent in agent_roster_store.list_all()
            if not agent["enabled"]
        ],
        "uptime": f"{hours:02d}:{minutes:02d}:{secs:02d}",
    }


@router.get("/api/agents/roster")
async def roster():
    agents = agent_roster_store.list_all()
    return {
        "agents": agents,
        "total": len(agents),
        "enabled": sum(bool(agent["enabled"]) for agent in agents),
    }


@router.patch(
    "/api/agents/roster/{agent_id}",
    dependencies=[Depends(require_local_origin)],
)
async def set_roster_state(agent_id: str, payload: RosterStateRequest):
    try:
        agent = agent_roster_store.set_enabled(agent_id, payload.enabled)
    except AgentRosterError as error:
        status_code = 409 if str(error) == "core_agent_always_enabled" else 404
        raise HTTPException(
            status_code=status_code,
            detail={"code": str(error), "message": str(error).replace("_", " ")},
        ) from None
    return {"status": "ok", "agent": agent}


@router.post("/roster/visibility", dependencies=[Depends(require_local_origin)])
async def set_visibility(body: VisibilityRequest):
    """Compatibilidad: delega la visibilidad antigua al roster único."""
    agent_id = body.id if ":" in body.id else f"bundled:{body.id}"
    try:
        agent_roster_store.set_enabled(agent_id, not body.hidden)
    except AgentRosterError as error:
        status_code = 409 if str(error) == "core_agent_always_enabled" else 404
        raise HTTPException(
            status_code=status_code,
            detail={"code": str(error), "message": str(error).replace("_", " ")},
        ) from None
    hidden = [
        agent["nombre"]
        for agent in agent_roster_store.list_all()
        if not agent["enabled"]
    ]
    return {"status": "ok", "hidden": hidden}
