"""Loopback-only Ollama adapter for local text generation.

The endpoint is intentionally fixed to Ollama's default loopback listener.
Keeping it non-configurable prevents this provider from becoming an SSRF path.
"""

import base64
import json

import httpx

from app.core.config import DEFAULT_OLLAMA_MODEL
from app.core.providers.base import (
    ProviderConfigurationError,
    ProviderCredential,
    ProviderRequest,
    ProviderResponseError,
    ProviderResult,
    ProviderSpec,
    ProviderUnavailableError,
    ensure_supported_inputs,
    sanitized_http_error,
)

OLLAMA_CHAT_ENDPOINT = "http://127.0.0.1:11434/api/chat"


class OllamaProvider:
    spec = ProviderSpec(
        provider_id="ollama",
        display_label="Ollama",
        default_model=DEFAULT_OLLAMA_MODEL,
        requires_api_key=False,
        implementation_available=True,
        input_modalities=("text", "image"),
    )

    async def generate(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
    ) -> ProviderResult:
        ensure_supported_inputs(self.spec, request)
        message: dict[str, object] = {"role": "user", "content": request.prompt}
        if request.attachments:
            message["images"] = [
                base64.b64encode(attachment.data).decode("ascii")
                for attachment in request.attachments
            ]
        # Rol system nativo, antes del turno del usuario.
        messages: list[dict[str, object]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append(message)
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages,
            "stream": False,
        }
        if request.response_schema is not None:
            body["format"] = request.response_schema

        try:
            async with httpx.AsyncClient(
                timeout=request.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(OLLAMA_CHAT_ENDPOINT, json=body)
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise ProviderConfigurationError(
                    self.spec.provider_id,
                    "The selected Ollama model is not installed",
                ) from None
            raise sanitized_http_error(
                self.spec.provider_id,
                error.response.status_code,
                error.response.headers.get("Retry-After"),
            ) from None
        except httpx.TimeoutException:
            raise ProviderUnavailableError(
                self.spec.provider_id,
                "The local Ollama request timed out",
                reason="timeout",
            ) from None
        except httpx.RequestError:
            raise ProviderUnavailableError(
                self.spec.provider_id,
                "The local Ollama service is not reachable",
                reason="connection",
            ) from None

        try:
            payload = response.json()
            text = payload["message"]["content"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise ProviderResponseError(
                self.spec.provider_id,
                "Ollama returned an invalid response",
            ) from None

        if not isinstance(text, str) or not text:
            raise ProviderResponseError(
                self.spec.provider_id,
                "Ollama returned no generated text",
            )

        return ProviderResult(
            text=text,
            provider_id=self.spec.provider_id,
            model=request.model,
            metadata={
                "response_type": "ollama.chat",
                "finish_reason": payload.get("done_reason", "stop"),
            },
        )
