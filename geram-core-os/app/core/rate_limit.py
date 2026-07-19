"""Small in-process sliding-window limiter for the local HTTP chat surface."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._entries: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _evict(self, threshold: float) -> None:
        """Purga las claves ya vencidas: sin esto el mapa sólo crece."""
        for key in [k for k, v in self._entries.items() if not v or v[-1] <= threshold]:
            del self._entries[key]

    def check(self, key: str) -> None:
        now = time.monotonic()
        threshold = now - self.window_seconds
        with self._lock:
            self._evict(threshold)
            entries = self._entries[key]
            while entries and entries[0] <= threshold:
                entries.popleft()
            if len(entries) >= self.limit:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "code": "local_rate_limit",
                        "message": "Too many requests; try again shortly",
                    },
                )
            entries.append(now)


orchestrator_limiter = SlidingWindowLimiter(limit=30, window_seconds=60.0)


def enforce_orchestrator_rate_limit(request: Request) -> None:
    client = request.scope.get("client")
    host = str(client[0]) if client else "local"
    orchestrator_limiter.check(host)
