"""
Central configuration module for GERAM CORE OS.

Loads environment variables once and exposes a typed Settings object
consumed across the entire backend. Keeping this isolated means every
router/service imports from a single source of truth instead of calling
os.getenv() scattered across the codebase.
"""

import json
import math
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

# Load .env from project root regardless of current working directory.
# override=True es necesario porque /config/restart (app/api/config.py)
# relanza el proceso vía subprocess.Popen SIN pasar un env limpio — el
# nuevo proceso hereda el os.environ del proceso viejo, que ya trae
# cualquier valor que un load_dotenv() anterior haya vuelto a meter ahí.
# Sin override=True, python-dotenv NO pisa una variable que ya exista
# en el entorno heredado, así que .env recién editado por el panel de
# Configuración del HUD nunca se reflejaría tras un restart — el
# proceso seguiría usando el valor viejo para siempre.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
# `load_dotenv` mutates `os.environ`; preserve the process environment so
# imports/tests cannot leak runtime configuration into unrelated consumers.
_environment_before_dotenv = dict(os.environ)
load_dotenv(ROOT_DIR / ".env", override=True)
_runtime_environment = dict(os.environ)
os.environ.clear()
os.environ.update(_environment_before_dotenv)

DEFAULT_APP_HOST = "127.0.0.1"

# Nombre del workspace de usuario AISLADO por defecto (bajo $HOME). El
# explorador/editor/A.R.E.S. se limitan a esta carpeta; nunca al código
# fuente de GERAM. Se puede sobreescribir con GERAM_WORKSPACE_ROOT (.env).
DEFAULT_WORKSPACE_DIRNAME = "geram-workspace"
# Text providers selectable for the IRIS/ARES roles. The first four have
# first-party clients + optional legacy .env keys; the rest are added via the
# generic OpenAI-compatible adapter (+ Anthropic) and authenticate purely
# through the local credential pool (round-robin) — no .env field needed.
SUPPORTED_PROVIDER_IDS = frozenset({
    "openai", "gemini", "groq", "ollama",
    "anthropic",
    "mistral", "deepseek", "xai", "perplexity", "together",
    "openrouter", "cerebras", "fireworks", "moonshot",
})
DEFAULT_IRIS_PROVIDER = "gemini"
DEFAULT_ARES_PROVIDER = "openai"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OPENAI_MODEL = "gpt-5.1-codex"
# Reasoning effort applied to A.R.E.S. when it runs on a reasoning-capable model
# (o-series / gpt-5 / *-codex). Empty disables it. Non-reasoning models ignore it.
DEFAULT_ARES_REASONING_EFFORT = "medium"
REASONING_EFFORT_VALUES = ("minimal", "low", "medium", "high")
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OLLAMA_MODEL = "llama3.2:1b"
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 30.0
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0
DEFAULT_CREDENTIAL_POOL_MAX_ATTEMPTS = 3
MAX_MODEL_NAME_LENGTH = 200

PROVIDER_CREDENTIAL_FIELDS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    # Pool-only providers have no legacy .env key.  Keeping them in this
    # authority allows the credential pool validator and Settings UI to accept
    # them while ``provider_api_key`` still returns an empty legacy value.
    "anthropic": None,
    "mistral": None,
    "deepseek": None,
    "xai": None,
    "perplexity": None,
    "together": None,
    "openrouter": None,
    "cerebras": None,
    "fireworks": None,
    "moonshot": None,
}

PROVIDER_TIMEOUT_FIELDS = {
    "openai": "OPENAI_TIMEOUT_SECONDS",
    "gemini": "GEMINI_TIMEOUT_SECONDS",
    "groq": "GROQ_TIMEOUT_SECONDS",
    "ollama": "OLLAMA_TIMEOUT_SECONDS",
}


class SettingsValidationError(ValueError):
    """A configuration error that is safe to expose without its input value."""

    def __init__(self, field: str, code: str, message: str):
        self.field = field
        self.code = code
        super().__init__(message)


def resolve_local_data_dir(values: Mapping[str, str]) -> Path:
    """Resolve portable per-user application data on Linux, WSL and Windows."""
    configured = str(values.get("GERAM_LOCAL_DATA_DIR", "")).strip()
    if configured:
        candidate = Path(configured).expanduser()
        return (candidate if candidate.is_absolute() else ROOT_DIR / candidate).resolve()
    if os.name == "nt":
        base = str(values.get("LOCALAPPDATA", "")).strip()
        root = Path(base).expanduser() if base else Path.home() / "AppData" / "Local"
        return (root / "GERAM CORE OS").resolve()
    xdg_data_home = str(values.get("XDG_DATA_HOME", "")).strip()
    root = Path(xdg_data_home).expanduser() if xdg_data_home else Path.home() / ".local" / "share"
    return (root / "geram-core-os").resolve()


def developer_mode_enabled(config_path: Path | None = None) -> bool:
    """True si el Modo Desarrollador está activo en .geram-config.json.

    Se lee el JSON DIRECTAMENTE (sin importar user_config) para no crear un
    ciclo de imports; fail-safe: cualquier problema -> False (modo seguro).
    """
    candidates = [Path(config_path)] if config_path is not None else [
        resolve_local_data_dir(_runtime_environment) / "config" / "user-config.json",
        ROOT_DIR / ".geram-config.json",
    ]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return bool(data.get("privacy_controls", {}).get("developer_mode", False))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return False


def validate_workspace_root(
    configured_value: str | None,
    *,
    repository_root: Path = ROOT_DIR,
    home_directory: Path | None = None,
    create_default: bool = True,
    developer_mode: bool = False,
) -> Path:
    """Resolve a deliberately bounded local workspace without exposing it.

    SEGURIDAD (v3): por defecto el workspace editable es un directorio de
    usuario AISLADO (~/geram-workspace), NUNCA el código fuente de GERAM.
    Así el explorador/Monaco/A.R.E.S. solo ven los archivos del usuario y no
    pueden leer ni modificar los internos de la app (app/, agents/, etc.).
    Un valor explícito en GERAM_WORKSPACE_ROOT (.env) lo sobreescribe y debe
    existir; el default se crea solo si hace falta.
    """
    resolved_repository = repository_root.resolve()
    home = (home_directory or Path.home()).resolve()
    raw_value = (configured_value or "").strip()

    if raw_value:
        # Valor explícito (GERAM_WORKSPACE_ROOT): debe existir ya.
        try:
            candidate = Path(raw_value).expanduser()
            if not candidate.is_absolute():
                candidate = resolved_repository / candidate
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise SettingsValidationError(
                "GERAM_WORKSPACE_ROOT",
                "invalid_workspace_root",
                "GERAM_WORKSPACE_ROOT must identify an existing local directory",
            ) from None
        if not resolved.is_dir():
            raise SettingsValidationError(
                "GERAM_WORKSPACE_ROOT",
                "invalid_workspace_root",
                "GERAM_WORKSPACE_ROOT must identify an existing local directory",
            )
    elif developer_mode:
        # MODO DESARROLLADOR: se desbloquea la raíz del código de GERAM para
        # hackear los internos. Sigue acotado a esa raíz (403 fuera de ella);
        # los archivos sensibles (.env, credenciales) siguen protegidos por
        # los protected_paths del WorkspaceService (ver app/api/workspace.py).
        resolved = resolved_repository
    else:
        # Default AISLADO (modo seguro): ~/geram-workspace (se crea si no existe).
        candidate = home / DEFAULT_WORKSPACE_DIRNAME
        if create_default:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise SettingsValidationError(
                    "GERAM_WORKSPACE_ROOT",
                    "invalid_workspace_root",
                    "the default workspace directory could not be created",
                ) from None
        resolved = candidate.resolve()

    broad_roots = {
        Path(resolved.anchor).resolve(),
        home,
        home.parent,
    }
    for system_path in (
        "/bin",
        "/boot",
        "/dev",
        "/etc",
        "/lib",
        "/lib64",
        "/media",
        "/mnt",
        "/opt",
        "/proc",
        "/run",
        "/sbin",
        "/srv",
        "/sys",
        "/tmp",
        "/usr",
        "/var",
    ):
        path = Path(system_path)
        if path.exists():
            broad_roots.add(path.resolve())
    if resolved in broad_roots:
        raise SettingsValidationError(
            "GERAM_WORKSPACE_ROOT",
            "unsafe_workspace_root",
            "GERAM_WORKSPACE_ROOT is too broad for editable access",
        )

    static_root = (resolved_repository / "static").resolve()
    try:
        resolved.relative_to(static_root)
    except ValueError:
        pass
    else:
        raise SettingsValidationError(
            "GERAM_WORKSPACE_ROOT",
            "unsafe_workspace_root",
            "GERAM_WORKSPACE_ROOT cannot be inside the public static tree",
        )
    return resolved


@dataclass(frozen=True)
class RoleProviderSettings:
    provider: str
    model: str
    fallback_provider: str
    reasoning_effort: str = ""


def normalize_provider_id(
    value: str,
    field: str,
    *,
    allow_empty: bool = False,
) -> str:
    """Normalize and validate a supported provider identifier."""
    normalized = value.strip().lower()
    if not normalized and allow_empty:
        return ""
    if normalized not in SUPPORTED_PROVIDER_IDS:
        raise SettingsValidationError(
            field,
            "unsupported_provider",
            f"{field} must name a supported provider",
        )
    return normalized


def validate_model_name(value: str, field: str) -> str:
    """Validate a provider model identifier without maintaining a model allowlist."""
    normalized = value.strip()
    if not normalized:
        raise SettingsValidationError(field, "missing_model", f"{field} is required")
    if len(normalized) > MAX_MODEL_NAME_LENGTH:
        raise SettingsValidationError(
            field,
            "model_too_long",
            f"{field} exceeds the maximum allowed length",
        )
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise SettingsValidationError(
            field,
            "invalid_model",
            f"{field} contains control characters",
        )
    return normalized


def validate_timeout(value: str | float | int, field: str) -> float:
    """Parse a provider timeout constrained to one through 300 seconds."""
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise SettingsValidationError(
            field,
            "invalid_timeout",
            f"{field} must be a number between 1 and 300",
        ) from error
    if not math.isfinite(timeout) or not 1 <= timeout <= 300:
        raise SettingsValidationError(
            field,
            "invalid_timeout",
            f"{field} must be between 1 and 300",
        )
    return timeout


def validate_pool_max_attempts(value: str | int) -> int:
    """Constrain per-provider credential attempts to a small safe range."""
    try:
        attempts = int(value)
    except (TypeError, ValueError) as error:
        raise SettingsValidationError(
            "CREDENTIAL_POOL_MAX_ATTEMPTS",
            "invalid_pool_attempts",
            "CREDENTIAL_POOL_MAX_ATTEMPTS must be between 1 and 10",
        ) from error
    if isinstance(value, bool) or not 1 <= attempts <= 10:
        raise SettingsValidationError(
            "CREDENTIAL_POOL_MAX_ATTEMPTS",
            "invalid_pool_attempts",
            "CREDENTIAL_POOL_MAX_ATTEMPTS must be between 1 and 10",
        )
    return attempts


def _configured_value(
    values: Mapping[str, str],
    field: str,
    legacy_field: str,
    default: str,
) -> str:
    if field in values:
        return values[field]
    if legacy_field in values:
        return values[legacy_field]
    return default


def validate_reasoning_effort(value: str, field: str) -> str:
    """Validate an OpenAI reasoning effort level. Empty/"none"/"off" disable it."""
    normalized = value.strip().lower()
    if normalized in ("", "none", "off"):
        return ""
    if normalized not in REASONING_EFFORT_VALUES:
        raise SettingsValidationError(
            field,
            "invalid_reasoning_effort",
            f"{field} must be one of {REASONING_EFFORT_VALUES} or empty",
        )
    return normalized


def resolve_provider_configuration(
    values: Mapping[str, str],
) -> dict[str, str | float | int]:
    """Resolve and validate role mappings, models, fallbacks, and timeouts."""
    resolved: dict[str, str | float | int] = {
        "IRIS_PROVIDER": normalize_provider_id(
            values.get("IRIS_PROVIDER", DEFAULT_IRIS_PROVIDER),
            "IRIS_PROVIDER",
        ),
        "IRIS_MODEL": validate_model_name(
            _configured_value(
                values,
                "IRIS_MODEL",
                "GEMINI_MODEL",
                DEFAULT_GEMINI_MODEL,
            ),
            "IRIS_MODEL",
        ),
        "IRIS_FALLBACK_PROVIDER": normalize_provider_id(
            values.get("IRIS_FALLBACK_PROVIDER", ""),
            "IRIS_FALLBACK_PROVIDER",
            allow_empty=True,
        ),
        "ARES_PROVIDER": normalize_provider_id(
            values.get("ARES_PROVIDER", DEFAULT_ARES_PROVIDER),
            "ARES_PROVIDER",
        ),
        "ARES_MODEL": validate_model_name(
            _configured_value(
                values,
                "ARES_MODEL",
                "CODEX_MODEL",
                DEFAULT_OPENAI_MODEL,
            ),
            "ARES_MODEL",
        ),
        "ARES_FALLBACK_PROVIDER": normalize_provider_id(
            values.get("ARES_FALLBACK_PROVIDER", ""),
            "ARES_FALLBACK_PROVIDER",
            allow_empty=True,
        ),
        "ARES_REASONING_EFFORT": validate_reasoning_effort(
            str(values.get("ARES_REASONING_EFFORT", DEFAULT_ARES_REASONING_EFFORT)),
            "ARES_REASONING_EFFORT",
        ),
        "OPENAI_TIMEOUT_SECONDS": validate_timeout(
            values.get("OPENAI_TIMEOUT_SECONDS", DEFAULT_PROVIDER_TIMEOUT_SECONDS),
            "OPENAI_TIMEOUT_SECONDS",
        ),
        "GEMINI_TIMEOUT_SECONDS": validate_timeout(
            values.get("GEMINI_TIMEOUT_SECONDS", DEFAULT_PROVIDER_TIMEOUT_SECONDS),
            "GEMINI_TIMEOUT_SECONDS",
        ),
        "GROQ_TIMEOUT_SECONDS": validate_timeout(
            values.get("GROQ_TIMEOUT_SECONDS", DEFAULT_PROVIDER_TIMEOUT_SECONDS),
            "GROQ_TIMEOUT_SECONDS",
        ),
        "OLLAMA_TIMEOUT_SECONDS": validate_timeout(
            values.get("OLLAMA_TIMEOUT_SECONDS", DEFAULT_OLLAMA_TIMEOUT_SECONDS),
            "OLLAMA_TIMEOUT_SECONDS",
        ),
        "CREDENTIAL_POOL_MAX_ATTEMPTS": validate_pool_max_attempts(
            values.get(
                "CREDENTIAL_POOL_MAX_ATTEMPTS",
                DEFAULT_CREDENTIAL_POOL_MAX_ATTEMPTS,
            )
        ),
    }

    for role in ("IRIS", "ARES"):
        primary = str(resolved[f"{role}_PROVIDER"])
        fallback = str(resolved[f"{role}_FALLBACK_PROVIDER"])
        if fallback and fallback == primary:
            field = f"{role}_FALLBACK_PROVIDER"
            raise SettingsValidationError(
                field,
                "identical_primary_fallback",
                f"{field} must differ from {role}_PROVIDER",
            )

    return resolved


def _configured_local_cors_origins(
    port: int,
    configured_value: str | None = None,
) -> list[str]:
    """Return only the loopback origins used by the local HUD."""
    local_origins = [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]
    if configured_value is None:
        configured_value = os.getenv("CORS_ALLOWED_ORIGINS", "")
    configured = {
        origin.strip()
        for origin in configured_value.split(",")
        if origin.strip()
    }
    selected = [origin for origin in local_origins if origin in configured]
    return selected or local_origins


class Settings:
    """Validated application settings loaded from an environment-like mapping."""

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        create_runtime_dirs: bool = True,
    ):
        values = os.environ if environ is None else environ
        provider_configuration = resolve_provider_configuration(values)

        # Server
        self.APP_ENV = values.get("APP_ENV", "development")
        configured_host = str(values.get("APP_HOST", DEFAULT_APP_HOST)).strip().lower()
        self.APP_HOST = (
            configured_host
            if configured_host in {"127.0.0.1", "localhost", "::1"}
            else DEFAULT_APP_HOST
        )
        self.APP_PORT = int(values.get("APP_PORT", 8000))
        self.KIOSK_MODE = values.get("KIOSK_MODE", "true").lower() == "true"
        self.LOCAL_DATA_DIR = resolve_local_data_dir(values)
        self.DEVELOPER_MODE = developer_mode_enabled(
            self.LOCAL_DATA_DIR / "config" / "user-config.json"
        ) or developer_mode_enabled(ROOT_DIR / ".geram-config.json")
        self.WORKSPACE_ROOT = validate_workspace_root(
            values.get("GERAM_WORKSPACE_ROOT", ""),
            create_default=create_runtime_dirs,
            developer_mode=self.DEVELOPER_MODE,
        )

        # Role mappings
        self.IRIS_PROVIDER = str(provider_configuration["IRIS_PROVIDER"])
        self.IRIS_MODEL = str(provider_configuration["IRIS_MODEL"])
        self.IRIS_FALLBACK_PROVIDER = str(
            provider_configuration["IRIS_FALLBACK_PROVIDER"]
        )
        self.ARES_PROVIDER = str(provider_configuration["ARES_PROVIDER"])
        self.ARES_MODEL = str(provider_configuration["ARES_MODEL"])
        self.ARES_FALLBACK_PROVIDER = str(
            provider_configuration["ARES_FALLBACK_PROVIDER"]
        )
        self.ARES_REASONING_EFFORT = str(
            provider_configuration["ARES_REASONING_EFFORT"]
        )

        # Provider credentials and timeouts
        self.OPENAI_API_KEY = values.get("OPENAI_API_KEY", "")
        self.GEMINI_API_KEY = values.get("GEMINI_API_KEY", "")
        self.GROQ_API_KEY = values.get("GROQ_API_KEY", "")
        self.OPENAI_TIMEOUT_SECONDS = float(
            provider_configuration["OPENAI_TIMEOUT_SECONDS"]
        )
        self.GEMINI_TIMEOUT_SECONDS = float(
            provider_configuration["GEMINI_TIMEOUT_SECONDS"]
        )
        self.GROQ_TIMEOUT_SECONDS = float(
            provider_configuration["GROQ_TIMEOUT_SECONDS"]
        )
        self.OLLAMA_TIMEOUT_SECONDS = float(
            provider_configuration["OLLAMA_TIMEOUT_SECONDS"]
        )
        self.CREDENTIAL_POOL_MAX_ATTEMPTS = validate_pool_max_attempts(
            provider_configuration["CREDENTIAL_POOL_MAX_ATTEMPTS"]
        )

        local_data_dir = self.LOCAL_DATA_DIR
        try:
            local_data_dir.relative_to(ROOT_DIR.resolve())
        except ValueError:
            pass
        else:
            raise SettingsValidationError(
                "GERAM_LOCAL_DATA_DIR",
                "unsafe_local_data_dir",
                "GERAM_LOCAL_DATA_DIR must be outside the application source tree",
            )
        self.CREDENTIAL_STORE_PATH = (
            local_data_dir / "credentials" / "credential_pool.sqlite3"
        )

        # Deprecated model aliases retained for compatibility.
        self.GEMINI_MODEL = values.get("GEMINI_MODEL", self.IRIS_MODEL)
        self.CODEX_MODEL = values.get("CODEX_MODEL", self.ARES_MODEL)

        # Orchestrator
        self.ORCHESTRATOR_MODE = values.get("ORCHESTRATOR_MODE", "heuristic")
        self.DEFAULT_MODE = values.get("DEFAULT_MODE", "iris")

        # Agents.  The distributable repository keeps the established IRIS
        # agents next to ``geram-core-os/``.  Older Core builds accidentally
        # resolved the documented ``./agents`` default inside Core, where only
        # a package marker exists, so the dashboard could never discover the
        # real modules.  Preserve explicit custom paths while repairing that
        # historical default for existing .env files.
        configured_agents_dir = str(values.get("AGENTS_DIR", "./agents")).strip()
        sibling_agents_dir = ROOT_DIR.parent / "agents"
        if configured_agents_dir in {"", ".", "./agents", "agents"} and sibling_agents_dir.is_dir():
            agents_dir = sibling_agents_dir
        else:
            agents_dir = Path(configured_agents_dir or "agents").expanduser()
            if not agents_dir.is_absolute():
                agents_dir = ROOT_DIR / agents_dir
        self.AGENTS_DIR = agents_dir.resolve()
        self.AGENTS_AUTO_DISCOVER = (
            values.get("AGENTS_AUTO_DISCOVER", "true").lower() == "true"
        )

        # Integrations
        self.SUPABASE_URL = values.get("SUPABASE_URL", "")
        self.SUPABASE_KEY = values.get("SUPABASE_KEY", "")
        self.NOTION_API_KEY = values.get("NOTION_API_KEY", "")
        self.NOTION_DATABASE_ID = values.get("NOTION_DATABASE_ID", "")
        self.TELEGRAM_BOT_TOKEN = values.get("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_WEBHOOK_SECRET = values.get("TELEGRAM_WEBHOOK_SECRET", "")
        self.TELEGRAM_ALLOWED_CHAT_IDS = [
            item.strip()
            for item in values.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
            if item.strip()
        ]
        self.GOOGLE_CALENDAR_ACCESS_TOKEN = values.get(
            "GOOGLE_CALENDAR_ACCESS_TOKEN", ""
        )
        self.GOOGLE_CALENDAR_ID = values.get("GOOGLE_CALENDAR_ID", "primary")
        self.GOOGLE_ACCOUNT_EMAIL = values.get("GOOGLE_ACCOUNT_EMAIL", "")
        self.SPOTIFY_ACCESS_TOKEN = values.get("SPOTIFY_ACCESS_TOKEN", "")
        self.OBSIDIAN_VAULT_PATH = values.get("OBSIDIAN_VAULT_PATH", "")

        # Network
        self.TAILSCALE_HOSTNAME = values.get("TAILSCALE_HOSTNAME", "")
        self.TRUSTED_PROXY_NETWORK = values.get(
            "TRUSTED_PROXY_NETWORK",
            "100.64.0.0/10",
        )

        # Logging and telemetry
        self.LOG_LEVEL = values.get("LOG_LEVEL", "INFO")
        self.TELEMETRY_INTERVAL_SECONDS = float(
            values.get("TELEMETRY_INTERVAL_SECONDS", 1)
        )
        self.CODEX_SESSION_LOG_PATH = ROOT_DIR / values.get(
            "CODEX_SESSION_LOG_PATH",
            "./logs/sessions.jsonl",
        ).lstrip("./")

        # CORS
        self.CORS_ALLOWED_ORIGINS = _configured_local_cors_origins(
            self.APP_PORT,
            values.get("CORS_ALLOWED_ORIGINS", ""),
        )

        if create_runtime_dirs:
            self.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
            self.CODEX_SESSION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    def role_provider_settings(self, role: str) -> RoleProviderSettings:
        """Return the validated provider mapping for a product role."""
        normalized_role = role.strip().lower()
        if normalized_role == "iris":
            return RoleProviderSettings(
                self.IRIS_PROVIDER,
                self.IRIS_MODEL,
                self.IRIS_FALLBACK_PROVIDER,
            )
        if normalized_role == "ares":
            return RoleProviderSettings(
                self.ARES_PROVIDER,
                self.ARES_MODEL,
                self.ARES_FALLBACK_PROVIDER,
                self.ARES_REASONING_EFFORT,
            )
        raise SettingsValidationError(
            "role",
            "invalid_role",
            "Role must be either iris or ares",
        )

    def provider_api_key(self, provider_id: str) -> str:
        """Return the configured credential value for a supported provider."""
        normalized = normalize_provider_id(provider_id, "provider")
        credential_field = PROVIDER_CREDENTIAL_FIELDS.get(normalized)
        if not credential_field:
            return ""
        return str(getattr(self, credential_field))

    def provider_timeout(self, provider_id: str) -> float:
        """Return the configured timeout for a supported provider.

        Providers added via the pool (no dedicated *_TIMEOUT_SECONDS setting)
        fall back to the shared default instead of raising a KeyError.
        """
        normalized = normalize_provider_id(provider_id, "provider")
        field = PROVIDER_TIMEOUT_FIELDS.get(normalized)
        if field is None:
            return float(DEFAULT_PROVIDER_TIMEOUT_SECONDS)
        return float(getattr(self, field))


settings = Settings(_runtime_environment)
