"""
GERAM CORE OS — Backend Entry Point

Local-first, agentic developer-workflow operating environment.
This file wires together middleware, CORS, and the core route map.
Business logic (AI providers, WebSocket telemetry stream,
Terminal Watcher, Sandbox Guard) is intentionally left for follow-up
implementation passes — this establishes clean, production-worthy
infrastructure first.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.telegram_poller import poll_telegram_updates
from app.middleware.session_logging import SessionLoggingMiddleware
from app.api import orchestrator, agents, telemetry, config, workspace, ares_edits, terminal_watcher, user_config, github, preview, share, gcs, python_lsp, workspace_navigation, workspace_operations, instance, iris_proxy
from app.api import source_control
from app.api import testing
from app.core.user_config import CONFIG_PATH, load_config
from app.websocket import hud_socket


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reemplaza los antiguos @app.on_event("startup") (deprecados en
    # FastAPI a favor de lifespan). Ambos loops corren como tareas de
    # fondo independientes durante toda la vida del proceso — no hay
    # nada que limpiar explícitamente después del yield, mueren solas
    # con el proceso.
    #
    # Genera .geram-config.json con valores por defecto (0600) si no existe
    # todavía, para que el HUD siempre encuentre una configuración válida.
    try:
        load_config(CONFIG_PATH, create_if_missing=True)
    except (OSError, ValueError):
        # Un config corrupto no debe impedir el arranque; los endpoints y
        # los helpers fail-safe ya degradan a valores por defecto.
        pass
    # Workspace AISLADO (v3): si está vacío la primera vez, deja una nota de
    # bienvenida para que el explorador no aparezca vacío y quede claro que
    # este —y no el código de GERAM— es el espacio editable del usuario.
    try:
        workspace_root = settings.WORKSPACE_ROOT
        if workspace_root.is_dir() and not any(workspace_root.iterdir()):
            (workspace_root / "WELCOME.md").write_text(
                "# Your GERAM workspace\n\n"
                "This folder (`~/geram-workspace`) is your ISOLATED workspace.\n"
                "The explorer, Monaco editor, and A.R.E.S. can only view and modify\n"
                "files located HERE—never GERAM's internal code.\n\n"
                "Create or copy your projects into this folder to get started.\n",
                encoding="utf-8",
            )
    except OSError:
        pass
    asyncio.create_task(hud_socket.telemetry_broadcast_loop())
    asyncio.create_task(poll_telegram_updates())
    try:
        yield
    finally:
        workspace_navigation.stop_search_jobs()
        await python_lsp.python_lsp_manager.stop()
        # Corta cualquier "compartir en vivo" para no dejar el mini-server ni
        # el túnel cloudflared huérfanos exponiendo una página tras cerrar.
        share.share_manager.stop()


app = FastAPI(
    title="GERAM CORE OS",
    description="Local-first agentic operating environment for developer workflows.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def safe_provider_key_validation_error(
    request: Request,
    error: RequestValidationError,
):
    """Prevent provider-key request validation from echoing submitted input."""
    if request.url.path.startswith(("/config/provider-keys", "/api/workspace/")):
        code = (
            "invalid_workspace_request"
            if request.url.path.startswith("/api/workspace/")
            else "invalid_credential_request"
        )
        message = (
            "The local workspace request is invalid"
            if request.url.path.startswith("/api/workspace/")
            else "Credential request is invalid"
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": code,
                    "message": message,
                }
            },
        )
    return await request_validation_exception_handler(request, error)

# ------------------------------------------------------------------
# Middleware
# ------------------------------------------------------------------
app.add_middleware(SessionLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Route map
# ------------------------------------------------------------------
# /orchestrator/route      -> decides IRIS vs ARES, single entry point
#                             for HUD, Telegram, and GCS commands
app.include_router(orchestrator.router)

# /agents/                 -> list available + loaded agents
# /agents/load             -> hot-load a micro-agent via importlib
# /agents/{agent_name}     -> hot-unload + force gc.collect()
app.include_router(agents.router)

# /telemetry/snapshot       -> point-in-time CPU/RAM snapshot (psutil)
#                              live stream runs over /ws/hud (see below)
app.include_router(telemetry.router)

# /ws/hud                   -> single bidirectional channel: telemetry
#                              broadcast (every TELEMETRY_INTERVAL_SECONDS)
#                              + inbound HUD messages (handler is a
#                              placeholder for now, see hud_socket.py)
app.include_router(hud_socket.router)

# /config/keys              -> compatible masked environment configuration
# /config/provider-keys     -> safe metadata and local credential-pool CRUD
# /config/restart           -> restart the backend after environment updates
app.include_router(config.router)

# /api/workspace/tree      -> bounded relative file tree
# /api/workspace/file      -> read or atomically save existing text files
app.include_router(workspace.router)

# /api/ares/proposals -> bounded, reviewable existing-file edits
app.include_router(ares_edits.router)
app.include_router(terminal_watcher.router)
app.include_router(python_lsp.router)
app.include_router(workspace_navigation.router)
app.include_router(workspace_operations.router)
app.include_router(source_control.router)
app.include_router(testing.router)

# /api/config -> local profile / identity / privacy settings (.geram-config.json)
app.include_router(user_config.router)

# /api/github -> local, secure GitHub token store for Source Control sign-in
app.include_router(github.router)

# /preview/{path} -> saved workspace web files for the live-preview iframe
app.include_router(preview.router)

# /share/* -> exponer UNA página del workspace a la red (LAN + túnel) para
# compartirla con amigos. Control localhost-only; la sirve un proceso aparte.
app.include_router(share.router)

# /info -> roster de agentes (builtin + custom) para el HUD embebido de A.R.E.S.
app.include_router(instance.router)

# /api/gcs/* -> AI Operating Environment core: Permission Registry, Skill
# System, local Skill Retriever, Integration Hub, Agent Factory, Context
# Builder. Fully offline; localhost-only; no real external calls.
app.include_router(gcs.router)

# Same-origin proxy to IRIS (:8010) so the agents dashboard works under the
# Electron CSP (connect-src 'self'). See app/api/iris_proxy.py.
app.include_router(iris_proxy.router)

# ------------------------------------------------------------------
# Planned routes (not yet implemented — placeholders for roadmap clarity)
# ------------------------------------------------------------------
# TODO: POST /integrations/telegram/webhook -> remote command channel
# (secret token auth). Requiere HTTPS público (Tailscale Funnel) que no
# está configurado todavía — por ahora Telegram se maneja con
# long-polling (ver app/core/telegram_poller.py, lanzado en el lifespan
# de arriba). Migrar a webhook aquí cuando Funnel esté listo.
# GET  /integrations/notion/files       -> semantic file viewer (Supabase cache)
# POST /gcs/terminal/watch              -> Terminal Watcher error capture
# POST /gcs/sandbox/test                -> automated test + screenshot runner
# POST /gcs/sandbox/guard               -> destructive command confirmation gate
# POST /gcs/repo/{action}               -> Repo Agent (git automation)


@app.get("/health")
async def health_check():
    """Basic liveness check — useful for Tailscale/remote monitoring."""
    return {"status": "ok", "app_env": settings.APP_ENV, "kiosk_mode": settings.KIOSK_MODE}


# ------------------------------------------------------------------
# HUD static frontend
# ------------------------------------------------------------------
# Mounted LAST so it never shadows the API routes above — StaticFiles
# with html=True serves index.html at "/" and falls back to it for
# unknown paths, but explicit routes registered earlier still win.
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_ENV == "development",
        proxy_headers=False,
    )
