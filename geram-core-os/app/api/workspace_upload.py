"""Subida de archivos y carpetas al workspace, desde el explorador.

Un archivo por petición, con la ruta relativa en la query y los bytes en el
cuerpo: el mismo patrón que /api/media/attachments. Así no hace falta
python-multipart (una dependencia menos) y el cuerpo se puede acotar
mientras se recibe, en vez de después.

Toda la validación de ruta la sigue haciendo WorkspaceService: nada aquí
construye rutas por su cuenta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.workspace import workspace_service
from app.core.security import require_local_origin, require_localhost
from app.core.workspace import WorkspaceError


router = APIRouter(
    prefix="/api/workspace/upload",
    tags=["workspace-upload"],
    dependencies=[Depends(require_localhost), Depends(require_local_origin)],
)

# Más generoso que el límite de edición (1 MiB): meter un PNG o un binario de
# assets en tu proyecto es legítimo aunque Monaco no pueda abrirlo. Lo que sí
# se mantiene acotado es cuánto puede escribir una sola petición.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def _bounded_body(request: Request, limit: int) -> bytes:
    """Lee el cuerpo cortando en cuanto se pasa del límite.

    Se comprueba Content-Length primero para rechazar barato, pero no se
    confía en él: el conteo real manda mientras llegan los trozos.
    """
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > limit:
                raise HTTPException(
                    status_code=413,
                    detail={"code": "file_too_large", "message": "The file exceeds the upload limit"},
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_content_length", "message": "The request is invalid"},
            ) from None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail={"code": "file_too_large", "message": "The file exceeds the upload limit"},
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("")
async def upload_file(
    request: Request,
    path: str = Query(min_length=1, max_length=4096),
):
    data = await _bounded_body(request, MAX_UPLOAD_BYTES)
    if not data:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_file", "message": "The file is empty"},
        )
    try:
        return workspace_service.create_binary_file(path, data, MAX_UPLOAD_BYTES)
    except WorkspaceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error)},
        ) from None
