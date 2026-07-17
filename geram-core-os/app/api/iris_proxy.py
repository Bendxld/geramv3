"""Same-origin proxy to the IRIS backend (server.py, :8010).

The GERAM CORE OS HUD (served from :8000) shows and controls IRIS's background
agents. The Electron window's CSP restricts `connect-src` to 'self', so the
renderer cannot fetch IRIS on :8010 directly — this router forwards the small
`/agentes` surface through core-os so the dashboard talks to a single origin
and the tight CSP stays intact.

Localhost-only, like the rest of the API. IRIS is co-launched on the same
machine; if it is down the proxy returns 502, which the HUD renders as an
"IRIS is offline" message.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_local_origin, require_localhost

IRIS_BASE_URL = "http://127.0.0.1:8010"
_TIMEOUT = 5.0

router = APIRouter(
    prefix="/api/iris",
    tags=["iris"],
    dependencies=[Depends(require_localhost)],
)


class AgentToggle(BaseModel):
    suspendido: bool


@router.get("/agentes")
async def listar_agentes():
    """Proxy IRIS's agent list so the same-origin dashboard can read it."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{IRIS_BASE_URL}/agentes")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="IRIS is not reachable") from None


@router.post("/agentes/{nombre}", dependencies=[Depends(require_local_origin)])
async def toggle_agente(nombre: str, payload: AgentToggle):
    """Proxy suspend/reactivate to IRIS, surfacing its own status faithfully."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{IRIS_BASE_URL}/agentes/{nombre}",
                json=payload.model_dump(),
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="IRIS is not reachable") from None

    if response.status_code >= 400:
        # Pass through IRIS's own error (404 unknown agent, 409 núcleo, …).
        try:
            detail = response.json().get("detail", "IRIS rejected the request")
        except ValueError:
            detail = "IRIS rejected the request"
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()
