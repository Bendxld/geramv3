"""
Memory — GERAM Core System.

Two kinds of memory, kept strictly separate:

  * **Session memory** — ephemeral, per-session, in-process. It disappears
    when the process exits. Nothing is written to disk.
  * **Permanent memory** — durable across sessions. It is DISABLED by default,
    is never assumed, and is only ever written on an EXPLICIT call by an agent
    that holds the ``permanent_memory`` permission. Conversations are NEVER
    auto-saved.

Notion is an *integration*, not a memory backend — it lives in the Integration
Hub and is never used as automatic storage here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.gcs.permissions import Permission, permission_registry

MAX_SESSION_NOTES = 100
MAX_NOTE_LENGTH = 2_000


@dataclass
class _SessionBucket:
    notes: list[str] = field(default_factory=list)


class MemoryManager:
    """Ephemeral session memory + a guarded permanent-memory surface.

    Permanent memory is intentionally minimal here: the Core exposes the
    *state* and the permission gate, leaving durable storage as prepared
    infrastructure. This honors "never assume permanent memory" while keeping
    a single, auditable place where that policy is enforced.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionBucket] = {}

    # -- session memory (ephemeral) --------------------------------------
    def remember_session(self, session_id: str, note: str) -> bool:
        """Append an ephemeral note to a session. Bounded; never persisted."""
        key = str(session_id).strip()
        text = str(note).strip()[:MAX_NOTE_LENGTH]
        if not key or not text:
            return False
        bucket = self._sessions.setdefault(key, _SessionBucket())
        if len(bucket.notes) >= MAX_SESSION_NOTES:
            bucket.notes.pop(0)  # oldest-out, bounded footprint
        bucket.notes.append(text)
        return True

    def recall_session(self, session_id: str) -> list[str]:
        bucket = self._sessions.get(str(session_id).strip())
        return list(bucket.notes) if bucket else []

    def forget_session(self, session_id: str) -> None:
        self._sessions.pop(str(session_id).strip(), None)

    # -- permanent memory (guarded, explicit) ----------------------------
    def permanent_enabled(self, granted: list[str]) -> bool:
        """Permanent memory is available only when the permission is held."""
        return permission_registry.has(granted, Permission.PERMANENT_MEMORY)

    def memory_state(self, granted: list[str]) -> dict:
        """A sanitized snapshot of memory availability for the Context Builder.

        Never contains memory *contents* — only whether each tier is active.
        """
        return {
            "session": {"enabled": True, "note_count_policy": MAX_SESSION_NOTES},
            "permanent": {
                "enabled": self.permanent_enabled(granted),
                "auto_save": False,  # conversations are never auto-saved
            },
        }


# Singleton shared across the app lifespan.
memory_manager = MemoryManager()
