"""
Integration Hub — GERAM Core System.

Reusable infrastructure for third-party integrations. Spotify and Notion are
the two *initial* implementations that validate the architecture; new
integrations are added by registering another adapter, never by touching the
Core.

Three distinct states are modeled explicitly, because conflating them is how
security bugs happen:

    AVAILABLE   — the adapter exists in the hub (code is present).
        |
    CONNECTED   — local credentials/config are present (presence only, the
        |         value is NEVER read into a response).
        |
    AUTHORIZED  — a specific agent holds the matching permission AND the
                  sensitive action has been approved.

An agent NEVER gets access just because an integration exists or is connected.
The Permission Registry is always consulted. OAuth is intentionally NOT
implemented — connection is represented by secure placeholders (env-var
*presence*), and every adapter call is a LOCAL MOCK: no real network request is
ever made to Spotify, Notion, or anyone else.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings
from app.core.gcs.permissions import Permission, permission_registry

# Integration lifecycle states, ordered.
STATE_AVAILABLE = "available"
STATE_CONNECTED = "connected"


@dataclass(frozen=True)
class IntegrationAction:
    """One callable action an integration exposes."""

    name: str
    description: str
    # Mutating actions (play, pause, create page) are sensitive and always
    # require approval; read-only ones (status) do not.
    mutating: bool


@dataclass(frozen=True)
class ActionResult:
    """Outcome of invoking an integration action through the hub."""

    status: str  # "ok" | "approval_required" | "denied" | "unavailable"
    integration: str
    action: str
    detail: dict

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "integration": self.integration,
            "action": self.action,
            "detail": self.detail,
        }


class IntegrationAdapter(ABC):
    """Base contract every integration adapter implements."""

    id: str
    name: str
    description: str
    permission: Permission
    actions: dict[str, IntegrationAction]

    @abstractmethod
    def is_connected(self) -> bool:
        """True when local credentials/config are PRESENT (presence only).

        Implementations must never return, log, or expose the secret value.
        """

    @abstractmethod
    def _execute(self, action: str, params: dict) -> dict:
        """Perform the LOCAL MOCK for ``action``. No real network I/O."""

    # -- public surface ---------------------------------------------------
    def state(self) -> str:
        return STATE_CONNECTED if self.is_connected() else STATE_AVAILABLE

    def sanitized_status(self) -> dict:
        """Metadata safe to expose anywhere — never contains secrets."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "state": self.state(),
            "actions": [
                {"name": a.name, "description": a.description, "mutating": a.mutating}
                for a in self.actions.values()
            ],
        }

    def invoke(self, action: str, params: dict, *, granted: list[str], approved: bool) -> ActionResult:
        """Run an action, enforcing connection + permission + approval.

        Order of checks is deliberately fail-closed:
          1. action known?          -> else "denied"
          2. connected?             -> else "unavailable"
          3. permission granted?    -> else "denied"
          4. sensitive + approved?  -> else "approval_required"
          5. run the local mock.
        """
        spec = self.actions.get(action)
        if spec is None:
            return ActionResult("denied", self.id, action, {"reason": "unknown_action"})

        if not self.is_connected():
            return ActionResult(
                "unavailable", self.id, action, {"reason": "not_connected", "state": STATE_AVAILABLE}
            )

        decision = permission_registry.decide(granted, self.permission)
        if decision.outcome == "denied":
            return ActionResult("denied", self.id, action, decision.as_dict())

        # Sensitive/mutating actions never run automatically. Read-only actions
        # (status) are safe to run once the permission is held.
        if spec.mutating and not approved:
            return ActionResult(
                "approval_required",
                self.id,
                action,
                {"reason": "sensitive_operation", "permission": self.permission.value},
            )

        detail = self._execute(action, params or {})
        return ActionResult("ok", self.id, action, detail)


class SpotifyAdapter(IntegrationAdapter):
    """Spotify: play / pause / status. Local mock, no Web API calls."""

    id = "spotify"
    name = "Spotify"
    description = "Control local Spotify playback (mock adapter)."
    permission = Permission.SPOTIFY
    actions = {
        "play": IntegrationAction("play", "Resume or start playback.", mutating=True),
        "pause": IntegrationAction("pause", "Pause playback.", mutating=True),
        "status": IntegrationAction("status", "Report current playback state.", mutating=False),
    }

    def is_connected(self) -> bool:
        # Placeholder connection: presence of an access token, never its value.
        # No token is required to develop offline; this simply reflects state.
        return bool(os.environ.get("SPOTIFY_ACCESS_TOKEN", "").strip())

    def _execute(self, action: str, params: dict) -> dict:
        if action == "play":
            return {"playback": "playing", "mock": True}
        if action == "pause":
            return {"playback": "paused", "mock": True}
        return {"playback": "stopped", "device": None, "mock": True}


class NotionAdapter(IntegrationAdapter):
    """Notion: create page. Local mock, no Notion API calls."""

    id = "notion"
    name = "Notion"
    description = "Create Notion pages (mock adapter)."
    permission = Permission.NOTION
    actions = {
        "create_page": IntegrationAction("create_page", "Create a new page.", mutating=True),
    }

    def is_connected(self) -> bool:
        # Reuses the existing, already-validated env credential — presence only.
        return bool(settings.NOTION_API_KEY.strip())

    def _execute(self, action: str, params: dict) -> dict:
        title = str(params.get("title", "")).strip()[:200]
        return {"created": True, "title": title or "Untitled", "mock": True}


class IntegrationHub:
    """Registry of integration adapters + permission-aware dispatch."""

    def __init__(self, adapters: list[IntegrationAdapter] | None = None) -> None:
        default = adapters if adapters is not None else [SpotifyAdapter(), NotionAdapter()]
        self._adapters: dict[str, IntegrationAdapter] = {a.id: a for a in default}

    def list_integrations(self) -> list[dict]:
        return [a.sanitized_status() for a in self._adapters.values()]

    def get(self, integration_id: str) -> IntegrationAdapter | None:
        return self._adapters.get(str(integration_id).strip().lower())

    def invoke(
        self, integration_id: str, action: str, params: dict, *, granted: list[str], approved: bool
    ) -> ActionResult:
        adapter = self.get(integration_id)
        if adapter is None:
            return ActionResult(
                "denied", str(integration_id), str(action), {"reason": "unknown_integration"}
            )
        return adapter.invoke(action, params, granted=granted, approved=approved)


# Singleton shared across the app lifespan.
integration_hub = IntegrationHub()
