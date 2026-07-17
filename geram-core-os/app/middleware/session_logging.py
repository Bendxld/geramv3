"""
Session Logging Middleware for GERAM CORE OS.

Stamps every request with a session_id (reused if provided via the
X-Codex-Session-Id header, generated otherwise) and writes a structured
JSON log line per request. This is the backbone of the "clean Codex
trace" required for hackathon judging: every request/response pair is
traceable back to a single session_id, which can also be threaded through
Codex prompts/commits for end-to-end auditability.
"""

import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger("geram_core")
logger.setLevel(settings.LOG_LEVEL)

# File handler writes structured JSON lines for later audit/documentation
_file_handler = logging.FileHandler(settings.CODEX_SESSION_LOG_PATH)
_file_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_file_handler)


class SessionLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = request.headers.get("X-Codex-Session-Id", str(uuid.uuid4()))
        start_time = time.time()

        # Expose session_id to downstream route handlers via request.state
        request.state.session_id = session_id

        response = await call_next(request)

        log_entry = {
            "session_id": session_id,
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "latency_ms": round((time.time() - start_time) * 1000, 2),
            "timestamp": time.time(),
        }
        logger.info(json.dumps(log_entry))

        response.headers["X-Codex-Session-Id"] = session_id
        return response
