"""Gemini generateContent adapter for the provider registry."""

import base64
import json
from urllib.parse import quote

import httpx

from app.core.config import DEFAULT_GEMINI_MODEL, settings
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

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


class GeminiProvider:
    spec = ProviderSpec(
        provider_id="gemini",
        display_label="Gemini",
        default_model=DEFAULT_GEMINI_MODEL,
        input_modalities=("text", "image", "audio"),
    )

    async def generate(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
    ) -> ProviderResult:
        credential = require_credential(self.spec, credential)
        model_path = quote(request.model, safe="-._")
        url = GEMINI_ENDPOINT.format(model=model_path)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": credential._reveal(),
        }
        ensure_supported_inputs(self.spec, request)
        parts = [{"text": request.prompt}]
        parts.extend({
            "inlineData": {
                "mimeType": attachment.media_type,
                "data": base64.b64encode(attachment.data).decode("ascii"),
            }
        } for attachment in request.attachments)
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "maxOutputTokens": 8192,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if request.response_schema is not None:
            body["generationConfig"].update({
                "responseMimeType": "application/json",
                "responseJsonSchema": request.response_schema,
            })

        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=body)
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
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
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
                "response_type": "generateContent",
                "finish_reason": payload["candidates"][0].get("finishReason"),
            },
        )


async def call_gemini(prompt: str) -> dict[str, str]:
    """Compatibility wrapper for callers that still invoke Gemini directly."""
    result = await GeminiProvider().generate(
        ProviderRequest(
            prompt=prompt,
            model=settings.GEMINI_MODEL,
            timeout_seconds=settings.GEMINI_TIMEOUT_SECONDS,
            role="iris",
        ),
        ProviderCredential(
            provider_id="gemini",
            secret=settings.GEMINI_API_KEY,
        ),
    )
    return result.response_payload()
