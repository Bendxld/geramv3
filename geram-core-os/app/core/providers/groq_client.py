"""Groq chat-completions adapter for text-only generation."""

import json

import httpx

from app.core.config import DEFAULT_GROQ_MODEL
from app.core.providers.base import (
    ProviderCredential,
    ProviderRequest,
    ProviderResponseError,
    ProviderResult,
    ProviderSpec,
    ProviderUnavailableError,
    ensure_supported_inputs,
    require_credential,
    sanitized_http_error,
)

GROQ_CHAT_COMPLETIONS_ENDPOINT = (
    "https://api.groq.com/openai/v1/chat/completions"
)


class GroqProvider:
    spec = ProviderSpec(
        provider_id="groq",
        display_label="Groq",
        default_model=DEFAULT_GROQ_MODEL,
    )

    async def generate(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
    ) -> ProviderResult:
        credential = require_credential(self.spec, credential)
        ensure_supported_inputs(self.spec, request)
        headers = {
            "Authorization": f"Bearer {credential._reveal()}",
            "Content-Type": "application/json",
        }
        body = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.response_schema is not None:
            # Groq's JSON-object mode is broadly compatible across its hosted
            # models. The provider-neutral final schema remains authoritative.
            body["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    GROQ_CHAT_COMPLETIONS_ENDPOINT,
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
