"""Generic OpenAI-compatible chat-completions adapter.

Many text providers — Mistral, DeepSeek, xAI (Grok), Perplexity, Together,
OpenRouter, Cerebras, Fireworks, Moonshot, … — speak the exact OpenAI
`/chat/completions` dialect; only the base URL, default model, and display
label differ. This factory builds one provider per entry from that data
alone, reusing the same sanitized error handling as the first-party clients
(it is the Groq adapter generalized over its endpoint).

Credentials for these providers are supplied through the local credential
pool (round-robin), so no per-provider `.env` field or Settings attribute is
required — adding an entry here is all it takes to surface a new provider in
the catalog and the config UI.
"""

import json

import httpx

from app.core.providers.base import (
    ProviderCredential,
    ProviderRequest,
    ProviderResponseError,
    ProviderResult,
    ProviderSpec,
    ProviderUnavailableError,
    require_credential,
    sanitized_http_error,
)


class OpenAICompatibleProvider:
    """An AIProvider backed by any OpenAI `/chat/completions` endpoint."""

    def __init__(
        self,
        *,
        provider_id: str,
        display_label: str,
        endpoint: str,
        default_model: str,
    ):
        self.spec = ProviderSpec(
            provider_id=provider_id,
            display_label=display_label,
            default_model=default_model,
        )
        self._endpoint = endpoint

    async def generate(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
    ) -> ProviderResult:
        credential = require_credential(self.spec, credential)
        headers = {
            "Authorization": f"Bearer {credential._reveal()}",
            "Content-Type": "application/json",
        }
        body = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.response_schema is not None:
            # JSON-object mode is the broadly-portable structured-output knob
            # across OpenAI-compatible providers; the provider-neutral final
            # schema remains authoritative for shape.
            body["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    self._endpoint,
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise sanitized_http_error(
                self.spec.provider_id,
                error.response.status_code,
                error.response.headers.get("Retry-After"),
            ) from None
        except httpx.TimeoutException:
            raise ProviderUnavailableError(
                self.spec.provider_id,
                "Provider request timed out",
                reason="timeout",
            ) from None
        except httpx.RequestError:
            raise ProviderUnavailableError(
                self.spec.provider_id,
                "Provider connection failed",
                reason="connection",
            ) from None

        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise ProviderResponseError(
                self.spec.provider_id,
                "Provider returned an invalid response",
            ) from None

        if not isinstance(text, str) or not text:
            raise ProviderResponseError(
                self.spec.provider_id,
                "Provider returned no generated text",
            )

        return ProviderResult(
            text=text,
            provider_id=self.spec.provider_id,
            model=request.model,
            metadata={
                "response_type": "chat.completion",
                "finish_reason": payload["choices"][0].get("finish_reason"),
            },
        )


# Each entry becomes a selectable text provider with its own round-robin key
# pool. `default_model` is only the initial suggestion — the user overrides it
# per role in the config UI, and swaps the key(s) in the credential pool.
OPENAI_COMPATIBLE_PROVIDERS: tuple[dict[str, str], ...] = (
    {
        "provider_id": "mistral",
        "display_label": "Mistral",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "default_model": "mistral-large-latest",
    },
    {
        "provider_id": "deepseek",
        "display_label": "DeepSeek",
        "endpoint": "https://api.deepseek.com/chat/completions",
        "default_model": "deepseek-chat",
    },
    {
        "provider_id": "xai",
        "display_label": "xAI (Grok)",
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "default_model": "grok-2-latest",
    },
    {
        "provider_id": "perplexity",
        "display_label": "Perplexity",
        "endpoint": "https://api.perplexity.ai/chat/completions",
        "default_model": "sonar",
    },
    {
        "provider_id": "together",
        "display_label": "Together AI",
        "endpoint": "https://api.together.xyz/v1/chat/completions",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    {
        "provider_id": "openrouter",
        "display_label": "OpenRouter",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "default_model": "openai/gpt-4o-mini",
    },
    {
        "provider_id": "cerebras",
        "display_label": "Cerebras",
        "endpoint": "https://api.cerebras.ai/v1/chat/completions",
        "default_model": "llama-3.3-70b",
    },
    {
        "provider_id": "fireworks",
        "display_label": "Fireworks AI",
        "endpoint": "https://api.fireworks.ai/inference/v1/chat/completions",
        "default_model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    },
    {
        "provider_id": "moonshot",
        "display_label": "Moonshot (Kimi)",
        "endpoint": "https://api.moonshot.ai/v1/chat/completions",
        "default_model": "moonshot-v1-8k",
    },
)


def build_openai_compatible_providers() -> tuple[OpenAICompatibleProvider, ...]:
    """Instantiate one provider per OPENAI_COMPATIBLE_PROVIDERS entry."""
    return tuple(
        OpenAICompatibleProvider(**entry) for entry in OPENAI_COMPATIBLE_PROVIDERS
    )
