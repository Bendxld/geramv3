"""
User configuration — GERAM CORE OS (v3, Paso 2)

Local, per-user profile / identity / privacy settings persisted as a single
JSON file (`.geram-config.json`) in the project root. This is deliberately
SEPARATE from `.env` (provider credentials, handled by app/api/config.py):
this file holds non-secret personalization plus a `blocked_paths` privacy
list that the workspace reader consults before serving file contents.

The file is written with 0600 permissions (owner read/write only) and is
git-ignored — it can contain the user's name, age and a personal prompt.

Every read helper is fail-safe: if the file is missing or unreadable, callers
get validated defaults (in memory, no write) instead of an exception, so a
bad/absent config never takes down A.R.E.S., IRIS, or the workspace.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import ROOT_DIR

CONFIG_PATH = ROOT_DIR / ".geram-config.json"

# Vistas admitidas para la identidad del núcleo en el HUD.
CORE_IDENTITY_VIEWS = ("core", "pet", "minimal")

# Colores CSS: solo hex (#rgb / #rrggbb / #rrggbbaa). Restringir a hex evita
# inyección de CSS arbitrario cuando el valor se escribe en una variable
# --principal del HUD/Monaco.
_HEX_COLOR = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=120)
    age: int | None = Field(default=None, ge=0, le=150)
    system_prompt_override: str = Field(default="", max_length=8000)
    use_tts_notifications: bool = False


class UiTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_color: str = Field(default="#e84393", pattern=_HEX_COLOR)
    background_color: str = Field(default="#0a0a0f", pattern=_HEX_COLOR)
    accent_color: str = Field(default="#8d1f68", pattern=_HEX_COLOR)
    core_identity_view: str = "core"

    @field_validator("core_identity_view")
    @classmethod
    def _validar_identidad(cls, value: str) -> str:
        if value not in CORE_IDENTITY_VIEWS:
            raise ValueError(
                f"core_identity_view must be one of {CORE_IDENTITY_VIEWS}"
            )
        return value


class PrivacyControls(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Rutas/nombres que el Sandbox Guard/agentes NO deben leer. Puede ser un
    # nombre suelto (".env"), una ruta relativa ("secrets/prod.key") o una
    # ruta absoluta ("/etc/passwd").
    blocked_paths: list[str] = Field(
        default_factory=lambda: [".env", "/etc/passwd"]
    )

    # MODO DESARROLLADOR DE GERAM (v3, Paso 3): con False (default seguro) el
    # workspace editable es ~/geram-workspace. Con True se DESBLOQUEA la raíz
    # del código de GERAM para hackear los internos. Requiere reiniciar el
    # backend para aplicar (el workspace root se fija al arrancar). Ver
    # app/core/config.py (validate_workspace_root) y el banner del HUD.
    developer_mode: bool = False

    @field_validator("blocked_paths")
    @classmethod
    def _limpiar_rutas(cls, value: list[str]) -> list[str]:
        limpias: list[str] = []
        for raw in value:
            entry = str(raw).strip()
            if entry and entry not in limpias:
                limpias.append(entry)
        if len(limpias) > 256:
            raise ValueError("blocked_paths cannot exceed 256 entries")
        return limpias


class OnboardingState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Version of the in-app manual the user has explicitly dismissed.
    # Increment the frontend manual version when materially updating it.
    manual_version_seen: int = Field(default=0, ge=0, le=10000)


class GeramConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_profile: UserProfile = Field(default_factory=UserProfile)
    ui_theme: UiTheme = Field(default_factory=UiTheme)
    privacy_controls: PrivacyControls = Field(default_factory=PrivacyControls)
    onboarding: OnboardingState = Field(default_factory=OnboardingState)


def default_config() -> GeramConfig:
    """A fresh config with every documented default filled in."""
    return GeramConfig()


def _write_atomic_0600(path: Path, text: str) -> None:
    """Write `text` to `path` atomically with 0600 perms (owner-only)."""
    directory = path.parent
    handle, temporary = tempfile.mkstemp(dir=str(directory), prefix=".geram-config-", suffix=".tmp")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
        # os.replace preserva los permisos del temp (0600); reforzamos por si
        # el destino ya existía con otra máscara heredada.
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def save_config(config: GeramConfig, path: Path = CONFIG_PATH) -> GeramConfig:
    """Validate (already-typed) and persist the config with 0600 perms."""
    path = Path(path)
    text = json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    _write_atomic_0600(path, text)
    return config


def load_config(path: Path = CONFIG_PATH, *, create_if_missing: bool = False) -> GeramConfig:
    """Return the persisted config, or defaults.

    - Missing file: returns defaults; writes them to disk only if
      `create_if_missing` is True (used at app startup / first GET).
    - Corrupt / schema-invalid file: raised to the caller so the API can
      surface a 422; in-request fail-safe helpers below swallow it instead.
    """
    path = Path(path)
    if not path.exists():
        config = default_config()
        if create_if_missing:
            save_config(config, path)
        return config
    raw = json.loads(path.read_text(encoding="utf-8"))
    return GeramConfig.model_validate(raw)


def load_config_safe(path: Path = CONFIG_PATH) -> GeramConfig:
    """Like load_config but never raises — returns defaults on any problem.

    Used by request-time consumers (system prompt injection, blocked_paths)
    where a broken config must degrade gracefully, not crash the flow.
    """
    try:
        return load_config(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return default_config()


def system_prompt_override(path: Path = CONFIG_PATH) -> str:
    """The user's global system prompt, or '' if unset/unavailable."""
    return load_config_safe(path).user_profile.system_prompt_override.strip()


def _normalize(entry: str) -> str:
    return entry.strip().strip("/").casefold()


def is_path_blocked(relative_path: str, name: str | None = None, path: Path = CONFIG_PATH) -> bool:
    """True if `relative_path` (or its basename `name`) matches a blocked entry.

    Matching is intentionally broad so a single ".env" entry protects the file
    anywhere in the tree: an entry matches when it equals the basename, equals
    the whole relative path, or is a trailing path segment of it.
    """
    blocked = load_config_safe(path).privacy_controls.blocked_paths
    if not blocked:
        return False
    rel = _normalize(relative_path)
    base = _normalize(name if name is not None else relative_path.rsplit("/", 1)[-1])
    rel_parts = rel.split("/") if rel else []
    for raw_entry in blocked:
        entry = _normalize(raw_entry)
        if not entry:
            continue
        if entry == base or entry == rel:
            return True
        entry_parts = entry.split("/")
        # "secrets/prod.key" bloquea ".../secrets/prod.key"
        if len(entry_parts) <= len(rel_parts) and rel_parts[len(rel_parts) - len(entry_parts):] == entry_parts:
            return True
    return False
