"""Focused tests for role routing and one-shot provider fallback."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from starlette.requests import Request

from app.core.providers.base import (
    ProviderAttachment,
    ProviderConfigurationError,
    ProviderCredential,
    ProviderRequest,
    ProviderResult,
    ProviderSpec,
    ProviderUnavailableError,
    ProviderUnsupportedInputError,
)


with (
    patch.dict(os.environ, {}, clear=True),
    patch("dotenv.load_dotenv", return_value=False),
    patch("pathlib.Path.mkdir"),
):
    from app.api import orchestrator
    from app.core.config import Settings
    from app.core.providers.registry import (
        ProviderDispatchResult,
        ProviderRegistry,
    )
    from app.core.providers import (
        gemini_client,
        groq_client,
        ollama_client,
        openai_client,
    )


class FakeProvider:
    def __init__(self, provider_id: str, *, error=None):
        self.spec = ProviderSpec(
            provider_id=provider_id,
            display_label=provider_id.title(),
            default_model=f"{provider_id}-default-model",
        )
        self.error = error
        self.calls = []

    async def generate(self, request, credential):
        self.calls.append((request, credential))
        if self.error is not None:
            raise self.error
        return ProviderResult(
            text=f"response-from-{self.spec.provider_id}",
            provider_id=self.spec.provider_id,
            model=request.model,
        )


def _settings(**overrides) -> Settings:
    values = {
        "OPENAI_API_KEY": "unit-test-openai-credential",
        "GEMINI_API_KEY": "unit-test-gemini-credential",
        "GROQ_API_KEY": "unit-test-groq-credential",
    }
    values.update(overrides)
    return Settings(values, create_runtime_dirs=False)


def _registry(*providers: FakeProvider) -> ProviderRegistry:
    return ProviderRegistry(providers, credential_pool=None)


class StubAsyncClient:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.last_post = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, **kwargs):
        self.last_post = (url, kwargs)
        return self.response


def _response(
    status_code: int,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request("POST", "https://provider.invalid/test")
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=request,
    )


def _provider_request(model: str, *, structured: bool = False) -> ProviderRequest:
    return ProviderRequest(
        prompt="unit-test prompt",
        model=model,
        timeout_seconds=30,
        role="iris",
        response_schema=(
            {"type": "object", "properties": {"value": {"type": "string"}}}
            if structured else None
        ),
        response_schema_name="unit_test_schema",
    )


def _credential(provider_id: str) -> ProviderCredential:
    return ProviderCredential(
        provider_id=provider_id,
        secret=f"unit-test-{provider_id}-credential",
    )


class ProviderAdapterTests(unittest.TestCase):
    def test_multimodal_payloads_are_encoded_only_at_provider_boundary(self):
        attachment = ProviderAttachment(
            media_type="image/png", data=b"\x89PNG\r\n\x1a\nimage", filename="image.png"
        )
        request = ProviderRequest(
            prompt="describe",
            model="vision-model",
            timeout_seconds=30,
            role="iris",
            attachments=(attachment,),
        )
        gemini = StubAsyncClient(_response(200, {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]
        }))
        with patch.object(gemini_client.httpx, "AsyncClient", return_value=gemini):
            asyncio.run(gemini_client.GeminiProvider().generate(request, _credential("gemini")))
        parts = gemini.last_post[1]["json"]["contents"][0]["parts"]
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")
        self.assertNotIn(repr(attachment.data), str(gemini.last_post))

        groq_request = ProviderRequest(
            prompt="describe", model="text-model", timeout_seconds=30,
            role="iris", attachments=(attachment,),
        )
        with self.assertRaises(ProviderUnsupportedInputError):
            asyncio.run(groq_client.GroqProvider().generate(groq_request, _credential("groq")))

    def test_provider_specific_structured_output_options_are_normalized(self):
        cases = (
            (
                gemini_client,
                gemini_client.GeminiProvider(),
                {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]},
                lambda body: (
                    body["generationConfig"]["responseMimeType"] == "application/json"
                    and body["generationConfig"]["responseJsonSchema"]["type"] == "object"
                ),
            ),
            (
                openai_client,
                openai_client.OpenAIProvider(),
                {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]},
                lambda body: body["text"]["format"]["type"] == "json_schema",
            ),
            (
                groq_client,
                groq_client.GroqProvider(),
                {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]},
                lambda body: body["response_format"] == {"type": "json_object"},
            ),
            (
                ollama_client,
                ollama_client.OllamaProvider(),
                {"message": {"content": "{}"}, "done_reason": "stop"},
                lambda body: body["format"]["type"] == "object",
            ),
        )
        for module, provider, payload, assertion in cases:
            with self.subTest(provider=provider.spec.provider_id):
                client = StubAsyncClient(_response(200, payload))
                with patch.object(module.httpx, "AsyncClient", return_value=client):
                    result = asyncio.run(provider.generate(
                        _provider_request("structured-model", structured=True),
                        None if provider.spec.provider_id == "ollama" else
                        _credential(provider.spec.provider_id),
                    ))
                self.assertTrue(assertion(client.last_post[1]["json"]))
                self.assertEqual(result.text, "{}")

    def test_gemini_adapter_parses_normalized_text_without_network(self):
        response = _response(
            200,
            {"candidates": [{"content": {"parts": [{"text": "gemini text"}]}}]},
        )
        client = StubAsyncClient(response)
        with patch.object(gemini_client.httpx, "AsyncClient", return_value=client):
            result = asyncio.run(
                gemini_client.GeminiProvider().generate(
                    _provider_request("gemini-model"),
                    _credential("gemini"),
                )
            )
        self.assertEqual(result.text, "gemini text")
        self.assertEqual(result.provider_id, "gemini")
        self.assertEqual(
            client.last_post[1]["json"]["generationConfig"]["thinkingConfig"],
            {"thinkingBudget": 0},
        )

    def test_openai_responses_adapter_parses_normalized_text_without_network(self):
        response = _response(
            200,
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "openai text"}
                        ],
                    }
                ]
            },
        )
        client = StubAsyncClient(response)
        with patch.object(openai_client.httpx, "AsyncClient", return_value=client):
            result = asyncio.run(
                openai_client.OpenAIProvider().generate(
                    _provider_request("openai-model"),
                    _credential("openai"),
                )
            )
        self.assertEqual(result.text, "openai text")
        self.assertEqual(result.provider_id, "openai")
        self.assertFalse(client.last_post[1]["json"]["store"])

    def test_groq_adapter_parses_normalized_text_without_network(self):
        response = _response(
            200,
            {"choices": [{"message": {"content": "groq text"}}]},
        )
        client = StubAsyncClient(response)
        with patch.object(groq_client.httpx, "AsyncClient", return_value=client):
            result = asyncio.run(
                groq_client.GroqProvider().generate(
                    _provider_request("groq-model"),
                    _credential("groq"),
                )
            )
        self.assertEqual(result.text, "groq text")
        self.assertEqual(result.provider_id, "groq")

    def test_ollama_adapter_is_keyless_and_fixed_to_loopback(self):
        response = _response(
            200,
            {"message": {"content": "local text"}, "done_reason": "stop"},
        )
        client = StubAsyncClient(response)
        with patch.object(ollama_client.httpx, "AsyncClient", return_value=client):
            result = asyncio.run(
                ollama_client.OllamaProvider().generate(
                    _provider_request("llama3.2:1b"),
                    None,
                )
            )
        self.assertEqual(result.text, "local text")
        self.assertEqual(result.provider_id, "ollama")
        self.assertEqual(client.last_post[0], "http://127.0.0.1:11434/api/chat")
        self.assertFalse(client.last_post[1]["json"]["stream"])
        self.assertFalse(ollama_client.OllamaProvider.spec.requires_api_key)
        self.assertTrue(ollama_client.OllamaProvider.spec.implementation_available)

    def test_upstream_error_does_not_expose_response_or_credential(self):
        test_value = "unit-test-sensitive-upstream-value"
        response = httpx.Response(
            401,
            text=test_value,
            request=httpx.Request("POST", "https://provider.invalid/test"),
        )
        client = StubAsyncClient(response)
        credential = ProviderCredential(provider_id="openai", secret=test_value)
        with (
            patch.object(openai_client.httpx, "AsyncClient", return_value=client),
            self.assertRaises(ProviderUnavailableError) as raised,
        ):
            asyncio.run(
                openai_client.OpenAIProvider().generate(
                    _provider_request("openai-model"),
                    credential,
                )
            )
        self.assertNotIn(test_value, str(raised.exception))

    def test_rate_limit_retry_after_is_parsed_without_raw_response(self):
        response = _response(
            429,
            {"error": "unit-test-upstream-body"},
            headers={"Retry-After": "120"},
        )
        client = StubAsyncClient(response)
        with (
            patch.object(openai_client.httpx, "AsyncClient", return_value=client),
            self.assertRaises(ProviderUnavailableError) as raised,
        ):
            asyncio.run(
                openai_client.OpenAIProvider().generate(
                    _provider_request("openai-model"),
                    _credential("openai"),
                )
            )
        self.assertEqual(raised.exception.reason, "rate_limit")
        self.assertEqual(raised.exception.retry_after_seconds, 120)
        self.assertNotIn("unit-test-upstream-body", str(raised.exception))

    def test_authentication_statuses_are_safely_classified(self):
        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                client = StubAsyncClient(
                    _response(status_code, {"error": "upstream-auth-body"})
                )
                with (
                    patch.object(
                        openai_client.httpx,
                        "AsyncClient",
                        return_value=client,
                    ),
                    self.assertRaises(ProviderUnavailableError) as raised,
                ):
                    asyncio.run(
                        openai_client.OpenAIProvider().generate(
                            _provider_request("openai-model"),
                            _credential("openai"),
                        )
                    )
                self.assertEqual(raised.exception.reason, "authentication")
                self.assertNotIn("upstream-auth-body", str(raised.exception))


class ProviderRoutingTests(unittest.TestCase):
    def test_default_role_provider_mappings(self):
        openai = FakeProvider("openai")
        gemini = FakeProvider("gemini")
        groq = FakeProvider("groq")
        registry = _registry(openai, gemini, groq)
        configuration = _settings()

        iris = asyncio.run(
            registry.generate_for_role("iris", "hello", configuration)
        )
        ares = asyncio.run(
            registry.generate_for_role("ares", "hello", configuration)
        )

        self.assertEqual(iris.metadata["provider"], "gemini")
        self.assertEqual(ares.metadata["provider"], "openai")
        self.assertEqual(len(gemini.calls), 1)
        self.assertEqual(len(openai.calls), 1)
        self.assertEqual(len(groq.calls), 0)

    def test_both_roles_can_select_the_same_provider(self):
        gemini = FakeProvider("gemini")
        registry = _registry(gemini)
        configuration = _settings(
            IRIS_PROVIDER="gemini",
            IRIS_MODEL="iris-model",
            ARES_PROVIDER="gemini",
            ARES_MODEL="ares-model",
        )

        asyncio.run(registry.generate_for_role("iris", "one", configuration))
        asyncio.run(registry.generate_for_role("ares", "two", configuration))

        self.assertEqual(len(gemini.calls), 2)
        self.assertEqual(
            [call[0].model for call in gemini.calls],
            ["iris-model", "ares-model"],
        )

    def test_roles_select_providers_independently(self):
        gemini = FakeProvider("gemini")
        groq = FakeProvider("groq")
        registry = _registry(gemini, groq)
        configuration = _settings(
            IRIS_PROVIDER="groq",
            IRIS_MODEL="groq-role-model",
            ARES_PROVIDER="gemini",
            ARES_MODEL="gemini-role-model",
        )

        iris = asyncio.run(
            registry.generate_for_role("iris", "one", configuration)
        )
        ares = asyncio.run(
            registry.generate_for_role("ares", "two", configuration)
        )

        self.assertEqual(iris.metadata["provider"], "groq")
        self.assertEqual(ares.metadata["provider"], "gemini")

    def test_eligible_failure_invokes_fallback_exactly_once(self):
        primary = FakeProvider(
            "gemini",
            error=ProviderUnavailableError(
                "gemini",
                "Provider rate limit reached",
                reason="rate_limit",
            ),
        )
        fallback = FakeProvider("groq")
        registry = _registry(primary, fallback)
        configuration = _settings(IRIS_FALLBACK_PROVIDER="groq")

        dispatch = asyncio.run(
            registry.generate_for_role("iris", "hello", configuration)
        )

        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(len(fallback.calls), 1)
        self.assertTrue(dispatch.metadata["fallback_used"])
        self.assertEqual(dispatch.metadata["provider"], "groq")
        self.assertEqual(dispatch.result["text"], "response-from-groq")

    def test_invalid_configuration_does_not_invoke_fallback(self):
        primary = FakeProvider("gemini")
        registry = _registry(primary)
        configuration = _settings()
        configuration.IRIS_FALLBACK_PROVIDER = "gemini"

        dispatch = asyncio.run(
            registry.generate_for_role("iris", "hello", configuration)
        )

        self.assertEqual(len(primary.calls), 0)
        self.assertFalse(dispatch.metadata["fallback_used"])
        self.assertEqual(
            dispatch.result["error_code"],
            "provider_configuration_error",
        )

    def test_configuration_failure_does_not_invoke_valid_fallback(self):
        primary = FakeProvider(
            "gemini",
            error=ProviderConfigurationError(
                "gemini",
                "Provider rejected the request or model configuration",
            ),
        )
        fallback = FakeProvider("groq")
        registry = _registry(primary, fallback)
        configuration = _settings(IRIS_FALLBACK_PROVIDER="groq")

        dispatch = asyncio.run(
            registry.generate_for_role("iris", "hello", configuration)
        )

        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(len(fallback.calls), 0)
        self.assertFalse(dispatch.metadata["fallback_used"])

    def test_both_provider_failures_return_a_sanitized_error(self):
        primary = FakeProvider(
            "gemini",
            error=ProviderUnavailableError(
                "gemini",
                "Provider request timed out",
                reason="timeout",
            ),
        )
        fallback = FakeProvider(
            "groq",
            error=ProviderUnavailableError(
                "groq",
                "Provider service is unavailable",
                reason="upstream",
            ),
        )
        registry = _registry(primary, fallback)
        configuration = _settings(IRIS_FALLBACK_PROVIDER="groq")

        dispatch = asyncio.run(
            registry.generate_for_role("iris", "hello", configuration)
        )

        rendered = str(dispatch.result)
        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(len(fallback.calls), 1)
        self.assertEqual(dispatch.result["error_code"], "provider_unavailable")
        self.assertNotIn("unit-test-gemini-credential", rendered)
        self.assertNotIn("unit-test-groq-credential", rendered)


class OrchestratorProviderIntegrationTests(unittest.TestCase):
    def test_orchestrator_preserves_shape_and_provider_metadata(self):
        dispatch = ProviderDispatchResult(
            result={"text": "normalized result"},
            metadata={
                "provider": "gemini",
                "model": "test-model",
                "fallback_used": False,
            },
        )
        with patch.object(
            orchestrator.provider_registry,
            "generate_for_role",
            new=AsyncMock(return_value=dispatch),
        ):
            response = asyncio.run(
                orchestrator.procesar_orquestacion(
                    "hello",
                    "hud_local",
                    force_mode="iris",
                    session_id="unit-test-session",
                )
            )

        self.assertEqual(response.mode, "iris")
        self.assertEqual(response.session_id, "unit-test-session")
        self.assertEqual(response.result, {"text": "normalized result"})
        self.assertEqual(response.metadata["source"], "hud_local")
        self.assertEqual(response.metadata["provider"], "gemini")
        self.assertFalse(response.metadata["fallback_used"])

    def test_route_uses_session_id_set_by_session_middleware(self):
        dispatch = ProviderDispatchResult(
            result={"text": "normalized result"},
            metadata={
                "provider": "openai",
                "model": "test-model",
                "fallback_used": False,
            },
        )
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/orchestrator/route",
                "headers": [],
            }
        )
        request.state.session_id = "propagated-session"
        payload = orchestrator.OrchestratorRequest(
            prompt="hello",
            source="hud_local",
            force_mode="ares",
        )

        with patch.object(
            orchestrator.provider_registry,
            "generate_for_role",
            new=AsyncMock(return_value=dispatch),
        ):
            response = asyncio.run(orchestrator.route_request(payload, request))

        self.assertEqual(response.session_id, "propagated-session")


if __name__ == "__main__":
    unittest.main()
