"""Anthropic (Claude) Messages API adapter for text-only generation.

Raw-httpx adapter — deliberately matching the other provider clients in this
package rather than pulling in the Anthropic SDK. The registry is a
provider-neutral abstraction (OpenAI, Gemini, Groq, … are all thin httpx
adapters behind the AIProvider protocol); keeping Claude the same shape avoids
a one-off SDK dependency and keeps every provider swappable.

Wire format per the Claude Messages API: POST /v1/messages with the
`x-api-key` + `anthropic-version` headers; `content` is a list of blocks and
the text lives in blocks of `type == "text"`.
"""

import json

import httpx

from app.core.config import DEFAULT_ANTHROPIC_MODEL
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

ANTHROPIC_MESSAGES_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Anthropic requires an explicit output cap; the HUD's turns are short, so a
# modest default keeps latency and cost bounded (the user can pick a smaller/
# larger model via the role's model field, but not max_tokens — this is it).
ANTHROPIC_MAX_TOKENS = 4096


class AnthropicProvider:
    spec = ProviderSpec(
        provider_id="anthropic",
        display_label="Anthropic (Claude)",
        default_model=DEFAULT_ANTHROPIC_MODEL,
    )

    async def generate(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
    ) -> ProviderResult:
        credential = require_credential(self.spec, credential)
        headers = {
            "x-api-key": credential._reveal(),
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        body = {
            "model": request.model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.response_schema is not None:
            # Structured outputs: same json_schema shape the OpenAI client uses,
            # so the app's (already strict-compatible) schemas port directly.
            body["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": request.response_schema,
                }
            }

        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    ANTHROPIC_MESSAGES_ENDPOINT,
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
            text_parts = [
                block["text"]
                for block in payload["content"]
                if block.get("type") == "text" and isinstance(block.get("text"), str)
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
                "response_type": "messages",
                "finish_reason": payload.get("stop_reason"),
            },
        )
