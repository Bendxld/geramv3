"""Compatibility wrapper for legacy callers of the OpenAI-backed Codex path."""

from app.core.config import settings
from app.core.providers.base import (
    ProviderConfigurationError,
    ProviderCredential,
    ProviderError,
    ProviderRequest,
)
from app.core.providers.openai_client import OpenAIProvider


async def call_codex(prompt: str) -> dict[str, object]:
    """Delegate the legacy call to the normalized OpenAI provider adapter."""
    credential = (
        ProviderCredential(
            provider_id="openai",
            secret=settings.OPENAI_API_KEY,
        )
        if settings.OPENAI_API_KEY
        else None
    )
    try:
        result = await OpenAIProvider().generate(
            ProviderRequest(
                prompt=prompt,
                model=settings.CODEX_MODEL,
                timeout_seconds=settings.OPENAI_TIMEOUT_SECONDS,
                role="ares",
            ),
            credential,
        )
    except ProviderConfigurationError as error:
        return {
            "status": "not_configured",
            "message": str(error),
            "error_code": error.code,
        }
    except ProviderError as error:
        return {
            "status": "error",
            "message": str(error),
            "error_code": error.code,
        }
    return result.response_payload()
