"""
Config Router — GERAM CORE OS

The Settings panel reads and writes an explicit subset of the real .env
file and can restart the backend to apply it. Credentials and existing
sensitive integration fields remain masked in every GET response.
"""

import re
import sqlite3
import subprocess

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, SecretStr

from app.core.config import (
    PROVIDER_CREDENTIAL_FIELDS,
    ROOT_DIR,
    SettingsValidationError,
    resolve_provider_configuration,
)
from app.core.credential_pool import (
    CredentialNotFoundError,
    CredentialPoolError,
    CredentialPoolValidationError,
    credential_pool_manager,
)
from app.core.providers.registry import provider_registry
from app.core.security import require_local_origin, require_localhost

router = APIRouter(
    prefix="/config",
    tags=["config"],
    dependencies=[Depends(require_localhost)],
)

ENV_PATH = ROOT_DIR / ".env"
LAUNCHER_PATH = ROOT_DIR / "launcher.py"
PYTHON_PATH = ROOT_DIR / "venv/bin/python"

# Existing sensitive fields keep their current masked response behavior.
CAMPOS_SENSIBLES = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "NOTION_API_KEY",
    "NOTION_DATABASE_ID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "GOOGLE_CALENDAR_CREDENTIALS_PATH",
    "GOOGLE_CALENDAR_ID",
    "GOOGLE_ACCOUNT_EMAIL",
    "SPOTIFY_ACCESS_TOKEN",
    "OBSIDIAN_VAULT_PATH",
]

CAMPOS_PROVEEDOR = [
    "IRIS_PROVIDER",
    "IRIS_MODEL",
    "IRIS_FALLBACK_PROVIDER",
    "ARES_PROVIDER",
    "ARES_MODEL",
    "ARES_FALLBACK_PROVIDER",
    "OPENAI_TIMEOUT_SECONDS",
    "GEMINI_TIMEOUT_SECONDS",
    "GROQ_TIMEOUT_SECONDS",
    "OLLAMA_TIMEOUT_SECONDS",
    "CREDENTIAL_POOL_MAX_ATTEMPTS",
]

CAMPOS_PERMITIDOS = CAMPOS_PROVEEDOR + CAMPOS_SENSIBLES

ROLE_PROVIDER_FIELDS = {
    "IRIS_PROVIDER": "IRIS",
    "IRIS_FALLBACK_PROVIDER": "IRIS",
    "ARES_PROVIDER": "ARES",
    "ARES_FALLBACK_PROVIDER": "ARES",
}


def _enmascarar(valor: str) -> str:
    """Muestra solo los últimos 4 caracteres — el resto se oculta."""
    if not valor:
        return ""
    if len(valor) <= 4:
        return "*" * len(valor)
    return "*" * (len(valor) - 4) + valor[-4:]


def _leer_env_actual() -> dict[str, str]:
    """Parsea el .env línea por línea (ignora comentarios/blancos)."""
    resultado: dict[str, str] = {}
    if not ENV_PATH.exists():
        return resultado

    for linea in ENV_PATH.read_text().splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, _, resto = limpia.partition("=")
        # El valor puede traer un comentario inline (ej. "123  # nota") —
        # solo nos interesa el token antes del primer espacio/#.
        valor = resto.split("#", 1)[0].strip()
        resultado[clave.strip()] = valor

    return resultado


def _actualizar_env_file(cambios: dict[str, str]) -> None:
    """Reescribe SOLO las líneas de los campos en `cambios`, por regex
    de '^CAMPO=', preservando comentarios/orden/resto del archivo —
    incluyendo comentarios inline en la misma línea (ej.
    "TELEGRAM_ALLOWED_CHAT_IDS=... # comma-separated whitelist")."""
    lineas = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    pendientes = dict(cambios)

    nuevas_lineas = []
    for linea in lineas:
        for clave in list(pendientes.keys()):
            patron = re.compile(rf"^{re.escape(clave)}=\S*")
            if patron.match(linea):
                valor = pendientes.pop(clave)
                linea = patron.sub(
                    lambda _match: f"{clave}={valor}",
                    linea,
                    count=1,
                )
                break
        nuevas_lineas.append(linea)

    # Campos que no existían en el archivo todavía — se agregan al final.
    for clave, valor in pendientes.items():
        nuevas_lineas.append(f"{clave}={valor}")

    contenido = "\n".join(nuevas_lineas) + "\n"
    ENV_PATH.write_text(contenido)


class ConfigKeysUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # rechaza cualquier campo fuera de la whitelist

    IRIS_PROVIDER: str | None = None
    IRIS_MODEL: str | None = None
    IRIS_FALLBACK_PROVIDER: str | None = None
    ARES_PROVIDER: str | None = None
    ARES_MODEL: str | None = None
    ARES_FALLBACK_PROVIDER: str | None = None
    OPENAI_TIMEOUT_SECONDS: str | float | int | None = None
    GEMINI_TIMEOUT_SECONDS: str | float | int | None = None
    GROQ_TIMEOUT_SECONDS: str | float | int | None = None
    OLLAMA_TIMEOUT_SECONDS: str | float | int | None = None
    CREDENTIAL_POOL_MAX_ATTEMPTS: str | int | None = None

    GEMINI_API_KEY: SecretStr | None = None
    OPENAI_API_KEY: SecretStr | None = None
    GROQ_API_KEY: SecretStr | None = None
    SUPABASE_URL: SecretStr | None = None
    SUPABASE_KEY: SecretStr | None = None
    NOTION_API_KEY: SecretStr | None = None
    NOTION_DATABASE_ID: SecretStr | None = None
    TELEGRAM_BOT_TOKEN: SecretStr | None = None
    TELEGRAM_ALLOWED_CHAT_IDS: SecretStr | None = None
    GOOGLE_CALENDAR_CREDENTIALS_PATH: SecretStr | None = None
    GOOGLE_CALENDAR_ID: SecretStr | None = None
    GOOGLE_ACCOUNT_EMAIL: SecretStr | None = None
    SPOTIFY_ACCESS_TOKEN: SecretStr | None = None
    OBSIDIAN_VAULT_PATH: SecretStr | None = None


class ProviderCredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str
    label: str
    secret: SecretStr
    enabled: bool = True
    priority: int = 100
    daily_request_cap: int | None = None


class ProviderCredentialPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    daily_request_cap: int | None = None
    secret: SecretStr | None = None


def _format_config_value(value: str | float | int) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _effective_configuration(actual: dict[str, str]) -> dict[str, str]:
    resolved = resolve_provider_configuration(actual)
    effective = {
        field: _format_config_value(resolved[field])
        for field in CAMPOS_PROVEEDOR
    }
    effective.update(
        {field: actual.get(field, "") for field in CAMPOS_SENSIBLES}
    )
    return effective


def _safe_http_validation_error(error: SettingsValidationError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "field": error.field,
            "code": error.code,
            "message": str(error),
        },
    )


def _submitted_values(payload: ConfigKeysUpdate) -> dict[str, str]:
    submitted: dict[str, str] = {}
    for field, value in payload.model_dump().items():
        if value is None:
            continue
        if isinstance(value, SecretStr):
            submitted[field] = value.get_secret_value()
        else:
            submitted[field] = str(value)
    return submitted


def _validated_changes(
    submitted: dict[str, str],
    actual: dict[str, str],
) -> dict[str, str]:
    try:
        before = _effective_configuration(actual)
    except SettingsValidationError as error:
        raise _safe_http_validation_error(error) from None

    unmasked_submitted = {
        field: value
        for field, value in submitted.items()
        if field not in CAMPOS_SENSIBLES
        or value != _enmascarar(actual.get(field, ""))
    }
    candidate = dict(actual)
    candidate.update(unmasked_submitted)

    try:
        resolved_candidate = resolve_provider_configuration(candidate)
    except SettingsValidationError as error:
        raise _safe_http_validation_error(error) from None

    normalized_submitted = dict(unmasked_submitted)
    for field in CAMPOS_PROVEEDOR:
        if field in normalized_submitted:
            normalized_submitted[field] = _format_config_value(
                resolved_candidate[field]
            )

    changes = {
        field: value
        for field, value in normalized_submitted.items()
        if value != before.get(field, actual.get(field, ""))
    }

    candidate.update(changes)
    resolved_candidate = resolve_provider_configuration(candidate)
    for field, role in ROLE_PROVIDER_FIELDS.items():
        if field not in changes:
            continue
        provider_id = str(resolved_candidate[field])
        if not provider_id:
            continue
        credential_field = PROVIDER_CREDENTIAL_FIELDS.get(provider_id)
        if credential_field is None:
            continue
        try:
            pool_has_credentials = credential_pool_manager.has_credentials(provider_id)
        except (CredentialPoolError, sqlite3.Error, OSError) as error:
            raise _credential_pool_http_error(error) from None
        if (
            not candidate.get(credential_field, "")
            and not pool_has_credentials
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "field": credential_field,
                    "code": "missing_provider_key",
                    "message": f"{credential_field} is required for {role}",
                },
            )

    return changes


@router.get("/keys")
async def obtener_keys():
    """Return public settings plainly and sensitive fields masked."""
    actuales = _leer_env_actual()
    try:
        effective = _effective_configuration(actuales)
    except SettingsValidationError as error:
        raise _safe_http_validation_error(error) from None
    return {
        campo: (
            _enmascarar(effective.get(campo, ""))
            if campo in CAMPOS_SENSIBLES
            else effective.get(campo, "")
        )
        for campo in CAMPOS_PERMITIDOS
    }


@router.post("/keys", dependencies=[Depends(require_local_origin)])
async def actualizar_keys(payload: ConfigKeysUpdate):
    actuales = _leer_env_actual()
    cambios = _validated_changes(_submitted_values(payload), actuales)

    if not cambios:
        return {"status": "sin_cambios", "actualizados": []}

    _actualizar_env_file(cambios)

    return {"status": "ok", "actualizados": list(cambios.keys())}


@router.get("/providers")
async def obtener_proveedores():
    """Return the public provider catalog with no credential information."""
    return provider_registry.catalog()


def _credential_pool_http_error(error: Exception) -> HTTPException:
    if isinstance(error, CredentialNotFoundError):
        status_code = 404
        message = "Credential was not found"
        code = error.code
    elif isinstance(error, CredentialPoolValidationError):
        status_code = 422
        message = "Credential request is invalid"
        code = error.code
    else:
        status_code = 503
        message = "Credential store is unavailable"
        code = "credential_pool_error"
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@router.get("/provider-keys")
async def listar_credenciales_proveedor(provider: str | None = None):
    """Return only safe operational metadata for local credential pools."""
    try:
        credentials = credential_pool_manager.list_safe_metadata(provider)
    except (CredentialPoolError, sqlite3.Error, OSError) as error:
        raise _credential_pool_http_error(error) from None
    return {"credentials": credentials}


@router.post(
    "/provider-keys",
    status_code=201,
    dependencies=[Depends(require_local_origin)],
)
async def crear_credencial_proveedor(payload: ProviderCredentialCreate):
    """Store a new provider credential without echoing its secret."""
    try:
        metadata = credential_pool_manager.add_credential(
            payload.provider,
            payload.label,
            payload.secret.get_secret_value(),
            enabled=payload.enabled,
            priority=payload.priority,
            daily_request_cap=payload.daily_request_cap,
        )
    except (CredentialPoolError, sqlite3.Error, OSError) as error:
        raise _credential_pool_http_error(error) from None
    return {"status": "created", "credential": metadata}


@router.patch(
    "/provider-keys/{credential_id}",
    dependencies=[Depends(require_local_origin)],
)
async def actualizar_credencial_proveedor(
    credential_id: str,
    payload: ProviderCredentialPatch,
):
    """Update safe metadata or atomically replace one stored secret."""
    submitted = payload.model_dump(exclude_unset=True)
    if not submitted:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_credential_request",
                "message": "Credential request is invalid",
            },
        )
    secret = submitted.pop("secret", None)
    if "label" in submitted and submitted["label"] is None:
        submitted["label"] = ""
    if "enabled" in submitted and submitted["enabled"] is None:
        submitted["enabled"] = ""
    if "priority" in submitted and submitted["priority"] is None:
        submitted["priority"] = ""
    if "secret" in payload.model_fields_set:
        submitted["secret_value"] = (
            secret.get_secret_value() if isinstance(secret, SecretStr) else secret
        )
    try:
        metadata = credential_pool_manager.update_credential(
            credential_id,
            **submitted,
        )
    except (CredentialPoolError, sqlite3.Error, OSError) as error:
        raise _credential_pool_http_error(error) from None
    return {"status": "updated", "credential": metadata}


@router.delete(
    "/provider-keys/{credential_id}",
    dependencies=[Depends(require_local_origin)],
)
async def eliminar_credencial_proveedor(credential_id: str):
    """Atomically remove secret material and its operational metadata."""
    try:
        credential_pool_manager.remove_credential(credential_id)
    except (CredentialPoolError, sqlite3.Error, OSError) as error:
        raise _credential_pool_http_error(error) from None
    return {"status": "deleted", "credential_id": credential_id}


@router.post("/restart", dependencies=[Depends(require_local_origin)])
async def reiniciar_backend():
    """
    Delegate restart to the same identity-safe local launcher used by the HUD.
    The detached helper validates PID, start time, root, argv, and cwd before
    stopping this process, then starts one local worker after a short delay.
    """
    subprocess.Popen(
        [
            str(PYTHON_PATH),
            str(LAUNCHER_PATH),
            "restart",
            "--delay",
            "1",
        ],
        cwd=ROOT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    return {
        "status": "restarting",
        "message": "The backend is restarting. Retry /health in a few seconds.",
    }
