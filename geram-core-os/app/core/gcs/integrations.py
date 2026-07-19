"""
Integration Hub — GERAM Core System.

Reusable infrastructure for bounded third-party and local integrations.

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
The Permission Registry is always consulted. Network adapters use fixed service
endpoints and return sanitized data; the local Obsidian adapter is confined to
the configured vault.
"""

from __future__ import annotations

import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from app.core.config import settings
from app.core.gcs.permissions import Permission, permission_registry

# Integration lifecycle states, ordered.
STATE_AVAILABLE = "available"
STATE_CONNECTED = "connected"
_SAFE_TABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


class IntegrationExecutionError(RuntimeError):
    """A sanitized operational integration failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: object | None = None,
    params: dict[str, object] | None = None,
) -> object:
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            response = client.request(
                method, url, headers=headers, json=payload, params=params
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise IntegrationExecutionError("integration_timeout", "The integration timed out") from None
    except httpx.HTTPStatusError as error:
        if error.response.status_code in {401, 403}:
            message = "The integration rejected its credentials"
        elif error.response.status_code == 429:
            message = "The integration rate limit was reached"
        else:
            message = "The integration request failed"
        raise IntegrationExecutionError("integration_http_error", message) from None
    except httpx.RequestError:
        raise IntegrationExecutionError("integration_unreachable", "The integration is unreachable") from None
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        raise IntegrationExecutionError("integration_response_error", "The integration returned invalid data") from None


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
        """Perform one bounded adapter action."""

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
          5. run the bounded adapter action.
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

        try:
            detail = self._execute(action, params or {})
        except IntegrationExecutionError as error:
            return ActionResult(
                "unavailable", self.id, action,
                {"reason": error.code, "message": str(error)},
            )
        return ActionResult("ok", self.id, action, detail)


class SpotifyAdapter(IntegrationAdapter):
    """Spotify Web API: play, pause, and sanitized playback status."""

    id = "spotify"
    name = "Spotify"
    description = "Control Spotify playback through the configured account credential."
    permission = Permission.SPOTIFY
    actions = {
        "play": IntegrationAction("play", "Resume or start playback.", mutating=True),
        "pause": IntegrationAction("pause", "Pause playback.", mutating=True),
        "status": IntegrationAction("status", "Report current playback state.", mutating=False),
    }

    def is_connected(self) -> bool:
        return bool(settings.SPOTIFY_ACCESS_TOKEN.strip())

    def _execute(self, action: str, params: dict) -> dict:
        token = settings.SPOTIFY_ACCESS_TOKEN.strip()
        headers = {"Authorization": f"Bearer {token}"}
        if action in {"play", "pause"}:
            _request_json(
                "PUT",
                f"https://api.spotify.com/v1/me/player/{action}",
                headers=headers,
            )
            return {"playback": "playing" if action == "play" else "paused"}
        payload = _request_json(
            "GET", "https://api.spotify.com/v1/me/player", headers=headers
        )
        if not isinstance(payload, dict) or not payload:
            return {"playback": "stopped", "track": None, "device": None}
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        device = payload.get("device") if isinstance(payload.get("device"), dict) else {}
        return {
            "playback": "playing" if payload.get("is_playing") else "paused",
            "track": str(item.get("name") or "")[:200] or None,
            "device": str(device.get("name") or "")[:120] or None,
        }


class NotionAdapter(IntegrationAdapter):
    """Notion API: create a page in the configured database."""

    id = "notion"
    name = "Notion"
    description = "Create pages in the configured Notion database."
    permission = Permission.NOTION
    actions = {
        "status": IntegrationAction("status", "Validate the configured workspace connection.", mutating=False),
        "create_page": IntegrationAction("create_page", "Create a new page.", mutating=True),
    }

    def is_connected(self) -> bool:
        return bool(settings.NOTION_API_KEY.strip() and settings.NOTION_DATABASE_ID.strip())

    def _execute(self, action: str, params: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {settings.NOTION_API_KEY.strip()}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        if action == "status":
            payload = _request_json(
                "GET",
                f"https://api.notion.com/v1/databases/{settings.NOTION_DATABASE_ID.strip()}",
                headers=headers,
            )
            return {"connected": True, "object": str(payload.get("object") or "database")[:40]}
        title = str(params.get("title", "")).strip()[:200] or "Untitled"
        payload = _request_json(
            "POST",
            "https://api.notion.com/v1/pages",
            headers=headers,
            payload={
                "parent": {"database_id": settings.NOTION_DATABASE_ID.strip()},
                "properties": {
                    "Name": {"title": [{"text": {"content": title}}]}
                },
            },
        )
        page_id = payload.get("id") if isinstance(payload, dict) else None
        return {"created": True, "title": title, "page_id": page_id}


class TelegramAdapter(IntegrationAdapter):
    id = "telegram"
    name = "Telegram"
    description = "Send a message only to a configured allowed chat."
    permission = Permission.TELEGRAM
    actions = {
        "status": IntegrationAction("status", "Validate the configured bot identity.", mutating=False),
        "send_message": IntegrationAction("send_message", "Send a Telegram message.", mutating=True),
    }

    def is_connected(self) -> bool:
        return bool(settings.TELEGRAM_BOT_TOKEN.strip() and settings.TELEGRAM_ALLOWED_CHAT_IDS)

    def _execute(self, action: str, params: dict) -> dict:
        if action == "status":
            payload = _request_json(
                "GET",
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN.strip()}/getMe",
            )
            result = payload.get("result") if isinstance(payload, dict) else {}
            return {
                "connected": True,
                "bot": str(result.get("username") or "")[:120] if isinstance(result, dict) else "",
            }
        allowed = settings.TELEGRAM_ALLOWED_CHAT_IDS
        requested = str(params.get("chat_id") or allowed[0]).strip()
        if requested not in allowed:
            raise IntegrationExecutionError("telegram_chat_denied", "The Telegram chat is not allowed")
        text = str(params.get("text", "")).strip()
        if not 1 <= len(text) <= 4096:
            raise IntegrationExecutionError("invalid_message", "Telegram text must be 1 to 4096 characters")
        payload = _request_json(
            "POST",
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN.strip()}/sendMessage",
            headers={"Content-Type": "application/json"},
            payload={"chat_id": requested, "text": text},
        )
        result = payload.get("result") if isinstance(payload, dict) else {}
        return {"sent": True, "message_id": result.get("message_id") if isinstance(result, dict) else None}


class SupabaseAdapter(IntegrationAdapter):
    id = "supabase"
    name = "Supabase"
    description = "Read or insert bounded rows through Supabase REST."
    permission = Permission.SUPABASE
    actions = {
        "select": IntegrationAction("select", "Read up to 100 rows.", mutating=False),
        "insert": IntegrationAction("insert", "Insert one row.", mutating=True),
    }

    def _base_url(self) -> str:
        value = settings.SUPABASE_URL.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise IntegrationExecutionError("invalid_supabase_url", "Supabase URL must be HTTPS")
        return value

    def is_connected(self) -> bool:
        try:
            self._base_url()
        except IntegrationExecutionError:
            return False
        return bool(settings.SUPABASE_KEY.strip())

    def _execute(self, action: str, params: dict) -> dict:
        table = str(params.get("table", "")).strip()
        if not _SAFE_TABLE.fullmatch(table):
            raise IntegrationExecutionError("invalid_table", "A valid Supabase table is required")
        headers = {
            "apikey": settings.SUPABASE_KEY.strip(),
            "Authorization": f"Bearer {settings.SUPABASE_KEY.strip()}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url()}/rest/v1/{table}"
        if action == "select":
            limit = params.get("limit", 25)
            if isinstance(limit, bool) or not isinstance(limit, int):
                limit = 25
            limit = max(1, min(limit, 100))
            payload = _request_json("GET", url, headers=headers, params={"select": "*", "limit": limit})
            rows = payload if isinstance(payload, list) else []
            return {"rows": rows[:limit], "count": min(len(rows), limit)}
        row = params.get("row")
        if not isinstance(row, dict) or not row or len(row) > 100:
            raise IntegrationExecutionError("invalid_row", "One bounded row object is required")
        headers["Prefer"] = "return=representation"
        payload = _request_json("POST", url, headers=headers, payload=row)
        rows = payload if isinstance(payload, list) else []
        return {"inserted": True, "rows": rows[:1]}


class GoogleCalendarAdapter(IntegrationAdapter):
    id = "google-calendar"
    name = "Google Calendar"
    description = "Read and create events using the configured OAuth credential."
    permission = Permission.CALENDAR
    actions = {
        "list_events": IntegrationAction("list_events", "List upcoming events.", mutating=False),
        "create_event": IntegrationAction("create_event", "Create an event.", mutating=True),
    }

    def is_connected(self) -> bool:
        return bool(settings.GOOGLE_CALENDAR_ACCESS_TOKEN.strip() and settings.GOOGLE_CALENDAR_ID.strip())

    def _execute(self, action: str, params: dict) -> dict:
        calendar_id = quote(settings.GOOGLE_CALENDAR_ID.strip(), safe="")
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
        headers = {"Authorization": f"Bearer {settings.GOOGLE_CALENDAR_ACCESS_TOKEN.strip()}"}
        if action == "list_events":
            maximum = params.get("max_results", 10)
            if isinstance(maximum, bool) or not isinstance(maximum, int):
                maximum = 10
            maximum = max(1, min(maximum, 50))
            query: dict[str, object] = {
                "maxResults": maximum, "singleEvents": "true", "orderBy": "startTime"
            }
            time_min = str(params.get("time_min", "")).strip()[:64]
            if time_min:
                query["timeMin"] = time_min
            payload = _request_json("GET", url, headers=headers, params=query)
            items = payload.get("items", []) if isinstance(payload, dict) else []
            return {"events": [{
                "id": item.get("id"), "summary": str(item.get("summary") or "")[:200],
                "start": item.get("start"), "end": item.get("end"),
            } for item in items[:maximum] if isinstance(item, dict)]}
        summary = str(params.get("summary", "")).strip()[:200]
        start = str(params.get("start", "")).strip()[:64]
        end = str(params.get("end", "")).strip()[:64]
        if not summary or not start or not end:
            raise IntegrationExecutionError("invalid_event", "Summary, start, and end are required")
        payload = _request_json(
            "POST", url, headers={**headers, "Content-Type": "application/json"},
            payload={"summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}},
        )
        return {"created": True, "event_id": payload.get("id") if isinstance(payload, dict) else None}


class ObsidianAdapter(IntegrationAdapter):
    id = "obsidian"
    name = "Obsidian"
    description = "Read and write Markdown notes inside the configured local vault."
    permission = Permission.OBSIDIAN
    actions = {
        "list_notes": IntegrationAction("list_notes", "List Markdown notes.", mutating=False),
        "read_note": IntegrationAction("read_note", "Read one Markdown note.", mutating=False),
        "write_note": IntegrationAction("write_note", "Write one Markdown note.", mutating=True),
    }

    def _root(self) -> Path:
        raw = settings.OBSIDIAN_VAULT_PATH.strip()
        if not raw:
            raise IntegrationExecutionError("obsidian_not_configured", "Obsidian vault is not configured")
        try:
            root = Path(raw).expanduser().resolve(strict=True)
        except OSError:
            raise IntegrationExecutionError("obsidian_unavailable", "Obsidian vault is unavailable") from None
        if not root.is_dir():
            raise IntegrationExecutionError("obsidian_unavailable", "Obsidian vault is unavailable")
        return root

    def _note(self, value: object, *, must_exist: bool) -> Path:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw or raw.startswith("/") or ".." in raw.split("/"):
            raise IntegrationExecutionError("invalid_note_path", "A relative note path is required")
        if not raw.lower().endswith(".md"):
            raw += ".md"
        root = self._root()
        path = (root / raw).resolve(strict=must_exist)
        try:
            path.relative_to(root)
        except ValueError:
            raise IntegrationExecutionError("invalid_note_path", "The note is outside the vault") from None
        return path

    def is_connected(self) -> bool:
        try:
            self._root()
            return True
        except IntegrationExecutionError:
            return False

    def _execute(self, action: str, params: dict) -> dict:
        if action == "list_notes":
            root = self._root()
            notes = []
            for path in root.rglob("*.md"):
                if path.is_file() and not path.is_symlink():
                    notes.append(path.relative_to(root).as_posix())
                    if len(notes) >= 500:
                        break
            return {"notes": sorted(notes), "truncated": len(notes) >= 500}
        path = self._note(params.get("path"), must_exist=action == "read_note")
        if action == "read_note":
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raise IntegrationExecutionError("note_unavailable", "The note could not be read") from None
            if len(content.encode("utf-8")) > 512 * 1024:
                raise IntegrationExecutionError("note_too_large", "The note exceeds 512 KiB")
            return {"path": path.relative_to(self._root()).as_posix(), "content": content}
        content = str(params.get("content", ""))
        if len(content.encode("utf-8")) > 512 * 1024:
            raise IntegrationExecutionError("note_too_large", "The note exceeds 512 KiB")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".note-", suffix=".tmp")
        try:
            if hasattr(os, "fchmod"):  # Unix-only; en Windows lo maneja el perfil de usuario
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise IntegrationExecutionError("note_write_failed", "The note could not be written") from None
        return {"written": True, "path": path.relative_to(self._root()).as_posix()}


class IntegrationHub:
    """Registry of integration adapters + permission-aware dispatch."""

    def __init__(self, adapters: list[IntegrationAdapter] | None = None) -> None:
        default = adapters if adapters is not None else [
            SpotifyAdapter(), NotionAdapter(), TelegramAdapter(),
            SupabaseAdapter(), GoogleCalendarAdapter(), ObsidianAdapter(),
        ]
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
