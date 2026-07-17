"""
Agents Router — GERAM CORE OS

Exposes hot-load / hot-unload endpoints for the /agents micro-agent system.
Backed by AgentRegistry (app/core/agent_loader.py), which handles the real
importlib + gc.collect() lifecycle.

Los agentes CUSTOM que crea el usuario NO viven aquí: se gestionan como
definiciones portables (JSON en el data dir del usuario) mediante el Agent
Factory de GCS —ver app/api/gcs.py, rutas /api/gcs/agents—, simétrico con los
Skills. Esto los mantiene fuera del árbol de código y sin ejecutar .py de
terceros.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.agent_loader import agent_registry

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentActionRequest(BaseModel):
    agent_name: str


@router.get("/")
async def list_agents():
    """Lists both available (on-disk) and currently loaded (in-memory) agents."""
    return {
        "available": agent_registry.list_available(),
        "loaded": agent_registry.list_loaded(),
    }


@router.post("/load")
async def load_agent(payload: AgentActionRequest):
    try:
        return agent_registry.load(payload.agent_name)
    except ModuleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{payload.agent_name}' not found in /agents")


@router.delete("/{agent_name}")
async def unload_agent(agent_name: str):
    try:
        return agent_registry.unload(agent_name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
