"""
Dynamic Agent Loader for GERAM CORE OS.

Manages hot-loading and hot-unloading of micro-agents living under /agents.
Unloading forces Python's module cache to drop the reference and triggers
garbage collection immediately, which is critical on resource-constrained
laptops where idle agents should not keep RAM reserved.

This module intentionally contains NO business logic about what an agent
*does* — it only manages the lifecycle (load/unload/list) of agent modules.
Actual agent implementations live as individual files under /agents.
"""

import importlib
import gc
import sys
import time
import re
from pathlib import Path

from app.core.config import settings


class AgentRegistry:
    """In-memory registry of currently loaded agent modules."""

    def __init__(self) -> None:
        self._loaded: dict[str, dict] = {}
        # Make /agents importable as a package namespace
        agents_parent = str(settings.AGENTS_DIR.parent)
        if agents_parent not in sys.path:
            sys.path.insert(0, agents_parent)

    def list_available(self) -> list[str]:
        """Scan /agents directory for candidate agent modules (*.py, no dunder)."""
        if not settings.AGENTS_DIR.exists():
            return []
        return sorted([
            p.stem
            for p in settings.AGENTS_DIR.glob("*.py")
            if not p.stem.startswith("_") and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", p.stem)
        ])

    def list_loaded(self) -> list[dict]:
        return [
            {"name": name, "loaded_at": meta["loaded_at"]}
            for name, meta in self._loaded.items()
        ]

    def load(self, agent_name: str) -> dict:
        """Load (or reload) an agent module by name via importlib."""
        if agent_name not in self.list_available():
            raise ModuleNotFoundError(agent_name)
        # Import lazily to avoid the roster -> loader singleton import cycle.
        # The roster is the per-user execution authority, not only UI state.
        from app.core.agent_roster import agent_roster_store

        if not agent_roster_store.is_enabled(f"bundled:{agent_name}"):
            raise PermissionError("agent_disabled")
        module_path = f"{settings.AGENTS_DIR.name}.{agent_name}"

        if agent_name in self._loaded:
            # Already loaded — reload to pick up any code changes on disk
            module = importlib.reload(sys.modules[module_path])
        else:
            module = importlib.import_module(module_path)

        self._loaded[agent_name] = {
            "module": module,
            "loaded_at": time.time(),
        }

        return {"status": "loaded", "agent": agent_name}

    def unload(self, agent_name: str) -> dict:
        """
        Unload an agent and force immediate RAM release.

        NOTE: if an agent spawned its own subprocess, thread, or open socket,
        that resource must be closed explicitly by the agent's own
        `shutdown()` hook (convention, not enforced here) BEFORE this runs —
        gc.collect() only reclaims what Python's reference counting allows.
        """
        if agent_name not in self._loaded:
            raise KeyError(f"Agent '{agent_name}' is not currently loaded")

        module_path = f"{settings.AGENTS_DIR.name}.{agent_name}"

        # 1. Drop local reference
        del self._loaded[agent_name]

        # 2. Purge from Python's module cache so it must be freshly
        #    re-imported next time (guarantees no stale bytecode lingers)
        if module_path in sys.modules:
            del sys.modules[module_path]

        # 3. Force garbage collection immediately
        collected = gc.collect()

        return {
            "status": "unloaded",
            "agent": agent_name,
            "gc_objects_collected": collected,
        }


# Singleton registry shared across the app lifespan
agent_registry = AgentRegistry()
