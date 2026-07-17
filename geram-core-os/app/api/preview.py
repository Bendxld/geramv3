"""
Live preview — GERAM CORE OS (v3)

Sirve archivos web GUARDADOS del workspace ACTIVO para el iframe de vista previa
del editor. Reutiliza `workspace_service.read_file`, así que hereda toda la
seguridad del workspace: acotado a la raíz, traversal `../`/absolutas -> 403,
rutas protegidas (.env, credenciales) y blocked_paths -> 403. Solo tipos web
de texto; nada binario ni fuera del workspace. `no-store` para que el
hot-reload siempre muestre la última versión (limpia la caché del iframe).
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.workspace import workspace_service
from app.core.security import require_localhost
from app.core.workspace import WorkspaceError

router = APIRouter(
    prefix="/preview",
    tags=["preview"],
    dependencies=[Depends(require_localhost)],
)

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}


@router.get("/{path:path}")
def preview_file(path: str):
    extension = ("." + path.rsplit(".", 1)[-1].lower()) if "." in path else ""
    media_type = _MEDIA_TYPES.get(extension)
    if not media_type:
        raise HTTPException(
            status_code=415,
            detail={"code": "unsupported_preview", "message": "Only text/web files can be previewed"},
        )
    try:
        content = workspace_service.read_file(path)["content"]
    except WorkspaceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from None
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "no-store, max-age=0"},
    )
