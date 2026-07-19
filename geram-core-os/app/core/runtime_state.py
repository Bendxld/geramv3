"""Per-OS-user HUD preferences stored outside the application checkout."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.core.config import settings


class RuntimePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    voice_enabled: bool = True
    vision_enabled: bool = False
    offline_forced: bool = False


class RuntimeStateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def path(self) -> Path:
        return settings.LOCAL_DATA_DIR / "runtime" / "preferences.json"

    def load(self) -> RuntimePreferences:
        with self._lock:
            try:
                return RuntimePreferences.model_validate_json(
                    self.path().read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError):
                return RuntimePreferences()

    def save(self, preferences: RuntimePreferences) -> RuntimePreferences:
        with self._lock:
            path = self.path()
            path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(path.parent, 0o700)
            descriptor, temporary = tempfile.mkstemp(
                dir=path.parent, prefix=".preferences-", suffix=".tmp"
            )
            try:
                if hasattr(os, "fchmod"):  # Unix-only; en Windows lo maneja el perfil de usuario
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(preferences.model_dump_json(indent=2) + "\n")
                os.replace(temporary, path)
                os.chmod(path, 0o600)
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
            return preferences

    def update(self, changes: dict[str, bool]) -> RuntimePreferences:
        current = self.load()
        updated = RuntimePreferences.model_validate(
            {**current.model_dump(mode="python"), **changes}
        )
        return self.save(updated)


runtime_state_store = RuntimeStateStore()
