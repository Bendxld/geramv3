"""OpenAI Responses API adapter for text-only generation."""

import json

import httpx

from app.core.config import DEFAULT_OPENAI_MODEL
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

OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"


class OpenAIProvider:
    spec = ProviderSpec(
        provider_id="openai",
        display_label="OpenAI",
        default_model=DEFAULT_OPENAI_MODEL,
    )

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
            "input": request.prompt,
            "store": False,
        }
        if request.response_schema is not None:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.response_schema_name,
                    "strict": True,
                    "schema": request.response_schema,
                }
            }

        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    OPENAI_RESPONSES_ENDPOINT,
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
            output = payload["output"]
            text_parts = [
                part["text"]
                for item in output
                if item.get("type") == "message"
                for part in item.get("content", [])
                if part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ]
        except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
            raise ProviderResponseError(
                self.spec.provider_id,
                "Provider returned an invalid response",
            ) from None

        text = "\n".join(part for part in text_parts if part)
        if not text:
            raise ProviderResponseError(
                self.spec.provider_id,
                "Provider returned no generated text",
            )

        return ProviderResult(
            text=text,
            provider_id=self.spec.provider_id,
            model=request.model,
            metadata={
                "response_type": "responses",
                "finish_reason": payload.get("status"),
            },
        )
