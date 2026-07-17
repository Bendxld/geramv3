"""
Compartir en vivo — router (GERAM CORE OS v3)

Controla la sesión de "compartir una página con amigos". Estos endpoints son
localhost-only: solo el usuario en su propia máquina puede iniciar/parar el
compartir. La página en sí la sirve un proceso aparte (ver share_service.py).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_localhost
from app.core.share_service import share_manager
from app.core.workspace import WorkspaceError

router = APIRouter(
    prefix="/share",
    tags=["share"],
    dependencies=[Depends(require_localhost)],
)


class ShareStartRequest(BaseModel):
    path: str
    tunnel: bool = False


@router.post("/start")
def start_share(body: ShareStartRequest):
    try:
        return share_manager.start(body.path, body.tunnel)
    except WorkspaceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "share_error", "message": str(error)},
        ) from None


@router.post("/stop")
def stop_share():
    return share_manager.stop()


@router.get("/status")
def share_status():
    return share_manager.status()
