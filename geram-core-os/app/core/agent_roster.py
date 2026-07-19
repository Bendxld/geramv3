"""Safe discovery plus per-user enable/disable state for every agent."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from app.core.agent_loader import agent_registry
from app.core.config import settings
from app.core.gcs.agent_factory import agent_factory


_SAFE_AGENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
CORE_AGENTS = frozenset({
    "director", "balancer", "memory", "context_engine", "personality",
    "escuchar", "habla", "offline_agent", "lock_agent", "control_agent",
})


def _label(value: str) -> str:
    cleaned = value.removesuffix("_agent").replace("_", " ").strip()
    return cleaned.title() if cleaned else value


class AgentRosterError(ValueError):
    pass


class AgentRosterStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def _state_path(self) -> Path:
        return settings.LOCAL_DATA_DIR / "agents" / "roster-state.json"

    def _disabled(self) -> set[str]:
        try:
            payload = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return set()
        values = payload.get("disabled", []) if isinstance(payload, dict) else []
        return {str(value) for value in values if isinstance(value, str)}

    def _write_disabled(self, disabled: set[str]) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=".roster-", suffix=".tmp"
        )
        try:
            if hasattr(os, "fchmod"):  # Unix-only; en Windows lo maneja el perfil de usuario
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"disabled": sorted(disabled)}, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _bundled(self, disabled: set[str]) -> list[dict[str, object]]:
        loaded = {item["name"] for item in agent_registry.list_loaded()}
        records = []
        directory = settings.AGENTS_DIR
        if not directory.is_dir():
            return records
        for path in sorted(directory.glob("*.py"), key=lambda item: item.name.casefold()):
            name = path.stem
            if name.startswith("_") or not _SAFE_AGENT.fullmatch(name):
                continue
            agent_id = f"bundled:{name}"
            core = name in CORE_AGENTS
            records.append({
                "id": agent_id,
                "nombre": name,
                "name": _label(name),
                "etiqueta": _label(name),
                "origin": "bundled",
                "profile": "ares" if name.startswith(("code", "proyectos")) else "iris",
                "core": core,
                "nucleo": core,
                "enabled": core or agent_id not in disabled,
                "suspendido": False if core else agent_id in disabled,
                "loaded": name in loaded,
                "status": "loaded" if name in loaded else "available",
            })
        return records

    def _defined(self, disabled: set[str]) -> list[dict[str, object]]:
        records = []
        for agent in agent_factory.list_all():
            agent_id = f"definition:{agent.id}"
            enabled = agent.status == "enabled" and agent_id not in disabled
            records.append({
                "id": agent_id,
                "nombre": agent.id,
                "name": agent.name,
                "etiqueta": agent.name,
                "origin": agent.origin,
                "profile": agent.profile,
                "core": agent.origin == "system",
                "nucleo": agent.origin == "system",
                "enabled": enabled,
                "suspendido": not enabled,
                "loaded": False,
                "status": "defined",
            })
        return records

    def list_all(self) -> list[dict[str, object]]:
        with self._lock:
            disabled = self._disabled()
            return self._bundled(disabled) + self._defined(disabled)

    def is_enabled(self, agent_id: str) -> bool:
        """Return the effective per-user execution state for one agent."""
        normalized = agent_id if ":" in agent_id else f"bundled:{agent_id}"
        with self._lock:
            return any(
                item["id"] == normalized and bool(item["enabled"])
                for item in self.list_all()
            )

    def set_enabled(self, agent_id: str, enabled: bool) -> dict[str, object]:
        with self._lock:
            records = {str(item["id"]): item for item in self.list_all()}
            record = records.get(agent_id)
            if record is None:
                raise AgentRosterError("agent_not_found")
            if bool(record["core"]) and not enabled:
                raise AgentRosterError("core_agent_always_enabled")
            disabled = self._disabled()
            if enabled:
                disabled.discard(agent_id)
            else:
                disabled.add(agent_id)
            self._write_disabled(disabled)
            if not enabled and str(record["origin"]) == "bundled":
                name = str(record["nombre"])
                if any(item["name"] == name for item in agent_registry.list_loaded()):
                    agent_registry.unload(name)
            return next(item for item in self.list_all() if item["id"] == agent_id)


agent_roster_store = AgentRosterStore()
