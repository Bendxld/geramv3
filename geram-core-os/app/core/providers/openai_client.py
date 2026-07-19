"""OpenAI Responses API adapter for text-only generation."""

import base64
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
    ensure_supported_inputs,
    require_credential,
    sanitized_http_error,
)

OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"


def _supports_reasoning(model: str) -> bool:
    """Whether a model accepts the Responses `reasoning.effort` parameter.

    Conservative allowlist: the o-series, the gpt-5 family, and any *-codex
    model. Non-reasoning models (e.g. gpt-4o) would reject the field, so they
    are excluded and the effort is silently dropped for them.
    """
    name = model.strip().lower()
    return (
        name.startswith(("o1", "o3", "o4", "gpt-5"))
        or "codex" in name
        or "reasoning" in name
    )


class OpenAIProvider:
    spec = ProviderSpec(
        provider_id="openai",
        display_label="OpenAI",
        default_model=DEFAULT_OPENAI_MODEL,
        input_modalities=("text", "image"),
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
        ensure_supported_inputs(self.spec, request)
        provider_input: object = request.prompt
        if request.attachments:
            content: list[dict[str, str]] = [
                {"type": "input_text", "text": request.prompt}
            ]
            content.extend({
                "type": "input_image",
                "image_url": (
                    f"data:{attachment.media_type};base64,"
                    + base64.b64encode(attachment.data).decode("ascii")
                ),
            } for attachment in request.attachments)
            provider_input = [{"role": "user", "content": content}]
        body = {
            "model": request.model,
            "input": provider_input,
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
        applied_effort = ""
        if request.reasoning_effort and _supports_reasoning(request.model):
            body["reasoning"] = {"effort": request.reasoning_effort}
            applied_effort = request.reasoning_effort

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
                "reasoning_effort": applied_effort,
            },
        )

    async def generate_stream(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
    ):
        """Stream Responses output as incremental text deltas.

        Yields dicts of the shape {"type": "delta", "text": ...} as tokens
        arrive and a final {"type": "final", "text": full, "metadata": {...}}.
        The full text is identical in shape to `generate`'s result, so the
        caller can validate and store it through the exact same path. Deltas are
        display-only and are never applied.
        """
        credential = require_credential(self.spec, credential)
        ensure_supported_inputs(self.spec, request)
        headers = {
            "Authorization": f"Bearer {credential._reveal()}",
            "Content-Type": "application/json",
        }
        provider_input: object = request.prompt
        if request.attachments:
            content: list[dict[str, str]] = [
                {"type": "input_text", "text": request.prompt}
            ]
            content.extend({
                "type": "input_image",
                "image_url": (
                    f"data:{attachment.media_type};base64,"
                    + base64.b64encode(attachment.data).decode("ascii")
                ),
            } for attachment in request.attachments)
            provider_input = [{"role": "user", "content": content}]
        body: dict[str, object] = {
            "model": request.model,
            "input": provider_input,
            "store": False,
            "stream": True,
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
        applied_effort = ""
        if request.reasoning_effort and _supports_reasoning(request.model):
            body["reasoning"] = {"effort": request.reasoning_effort}
            applied_effort = request.reasoning_effort

        chunks: list[str] = []
        status_final = "completed"
        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                async with client.stream(
                    "POST", OPENAI_RESPONSES_ENDPOINT, headers=headers, json=body
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise sanitized_http_error(
                            self.spec.provider_id,
                            response.status_code,
                            response.headers.get("Retry-After"),
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        event_type = event.get("type")
                        if event_type == "response.output_text.delta":
                            delta = event.get("delta")
                            if isinstance(delta, str) and delta:
                                chunks.append(delta)
                                yield {"type": "delta", "text": delta}
                        elif event_type in {"response.failed", "error", "response.error"}:
                            raise ProviderResponseError(
                                self.spec.provider_id,
                                "Provider reported a streaming error",
                            )
                        elif event_type == "response.completed":
                            completed = event.get("response")
                            if isinstance(completed, dict) and isinstance(
                                completed.get("status"), str
                            ):
                                status_final = completed["status"]
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

        text = "".join(chunks)
        if not text:
            raise ProviderResponseError(
                self.spec.provider_id,
                "Provider returned no generated text",
            )
        yield {
            "type": "final",
            "text": text,
            "metadata": {
                "response_type": "responses",
                "finish_reason": status_final,
                "reasoning_effort": applied_effort,
            },
        }

    async def respond_with_tools(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
        *,
        input_items: list,
        tools: list,
    ) -> dict:
        """Run one Responses round with function tools enabled.

        Returns {"function_calls": [{call_id, name, arguments}], "output_text":
        str | None, "status": str}. The caller runs the tool loop: it executes
        any function calls (read-only) and resends the accumulated input until
        the model emits the final structured message.
        """
        credential = require_credential(self.spec, credential)
        headers = {
            "Authorization": f"Bearer {credential._reveal()}",
            "Content-Type": "application/json",
        }
        body: dict[str, object] = {
            "model": request.model,
            "input": input_items,
            "store": False,
            "tools": tools,
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
        if request.reasoning_effort and _supports_reasoning(request.model):
            body["reasoning"] = {"effort": request.reasoning_effort}

        try:
            async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
                response = await client.post(
                    OPENAI_RESPONSES_ENDPOINT, headers=headers, json=body
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
                self.spec.provider_id, "Provider request timed out", reason="timeout"
            ) from None
        except httpx.RequestError:
            raise ProviderUnavailableError(
                self.spec.provider_id, "Provider connection failed", reason="connection"
            ) from None

        try:
            payload = response.json()
            output = payload.get("output", [])
        except (json.JSONDecodeError, AttributeError):
            raise ProviderResponseError(
                self.spec.provider_id, "Provider returned an invalid response"
            ) from None

        function_calls: list[dict] = []
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                function_calls.append({
                    "call_id": item.get("call_id"),
                    "name": item.get("name"),
                    "arguments": item.get("arguments"),
                })
            elif item.get("type") == "message":
                for part in item.get("content", []):
                    if (
                        isinstance(part, dict)
                        and part.get("type") == "output_text"
                        and isinstance(part.get("text"), str)
                    ):
                        text_parts.append(part["text"])

        joined = "\n".join(part for part in text_parts if part)
        return {
            "function_calls": function_calls,
            "output_text": joined or None,
            "status": payload.get("status"),
        }
