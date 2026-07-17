"""
Extensions API — import/create/use VS Code declarative contributions.

Monaco can consume a `.vsix`'s themes, snippets, grammars and language configs
(not its runtime code). This router lets the local user import a `.vsix` or a
loose theme/snippet/grammar JSON, create their own theme/snippet, and lets the
Monaco front-end pull the aggregated, editor-ready payloads.

Localhost-only; writes additionally require a local browser Origin. See
app/core/extensions_store.py for parsing/conversion.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core import extensions_store as store
from app.core.security import require_local_origin, require_localhost

router = APIRouter(
    prefix="/api/extensions",
    tags=["extensions"],
    dependencies=[Depends(require_localhost)],
)


def _handle(error: store.ExtensionError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": error.code, "message": str(error)})


@router.get("")
@router.get("/")
async def list_extensions():
    return {"extensions": store.list_extensions()}


@router.get("/themes")
async def list_themes():
    """Every imported theme as a monaco.editor.defineTheme payload."""
    return {"themes": store.all_themes()}


@router.get("/snippets")
async def list_snippets():
    return {"snippets": store.all_snippets()}


@router.get("/grammars")
async def list_grammars():
    return {"grammars": store.all_grammars()}


@router.get("/languages")
async def list_languages():
    return {"languages": store.all_languages()}


@router.post("/import", dependencies=[Depends(require_local_origin)])
async def import_extension(request: Request, filename: str = ""):
    """Import a raw .vsix or JSON body. The file is sent as the request body
    (no multipart dependency); its name comes in the `filename` query param."""
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail={"code": "empty", "message": "Empty file."})
    name = (filename or "").lower()
    try:
        if name.endswith(".vsix") or (data[:2] == b"PK" and not name.endswith(".json")):
            summary = store.import_vsix(bytes(data))
        else:
            summary = store.import_json_file(bytes(data), filename or "imported.json")
    except store.ExtensionError as error:
        raise _handle(error) from None
    return {"status": "ok", "extension": summary}


class CustomTheme(BaseModel):
    id: str = Field(min_length=1, max_length=99)
    label: str = Field(default="", max_length=120)
    theme: dict


@router.post("/theme", dependencies=[Depends(require_local_origin)])
async def create_theme(payload: CustomTheme):
    try:
        summary = store.save_custom_theme(payload.id, payload.label, payload.theme)
    except store.ExtensionError as error:
        raise _handle(error) from None
    return {"status": "ok", "extension": summary}


class CustomSnippet(BaseModel):
    id: str = Field(min_length=1, max_length=99)
    language: str = Field(default="*", max_length=64)
    snippets: dict


@router.post("/snippet", dependencies=[Depends(require_local_origin)])
async def create_snippet(payload: CustomSnippet):
    try:
        summary = store.save_custom_snippet(payload.id, payload.language, payload.snippets)
    except store.ExtensionError as error:
        raise _handle(error) from None
    return {"status": "ok", "extension": summary}


@router.get("/{ext_id}")
async def get_extension(ext_id: str):
    manifest = store.get_extension(ext_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown extension."})
    return manifest


@router.delete("/{ext_id}", dependencies=[Depends(require_local_origin)])
async def delete_extension(ext_id: str):
    if not store.delete_extension(ext_id):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown extension."})
    return {"status": "deleted", "id": ext_id}
