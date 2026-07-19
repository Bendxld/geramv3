"""Provider registry and role-aware primary/fallback dispatch."""

import asyncio
import json
import sqlite3

from dataclasses import dataclass
from typing import Iterable

from app.core.config import Settings, SettingsValidationError, settings
from app.core.credential_pool import (
    CredentialPoolError,
    CredentialPoolManager,
    credential_pool_manager,
)
from app.core.providers.base import (
    AIProvider,
    ProviderConfigurationError,
    ProviderCredential,
    ProviderError,
    ProviderRequest,
    ProviderAttachment,
    ProviderResponseError,
    ProviderUnavailableError,
    UnsupportedProviderError,
)
from app.core.providers.anthropic_client import AnthropicProvider
from app.core.providers.gemini_client import GeminiProvider
from app.core.providers.groq_client import GroqProvider
from app.core.providers.openai_client import OpenAIProvider
from app.core.providers.openai_compatible import build_openai_compatible_providers
from app.core.providers.ollama_client import OllamaProvider


@dataclass(frozen=True)
class ProviderDispatchResult:
    result: dict[str, object]
    metadata: dict[str, object]


class ProviderRegistry:
    """Resolve configured role providers and invoke at most one fallback."""

    def __init__(
        self,
        providers: Iterable[AIProvider] | None = None,
        *,
        credential_pool: CredentialPoolManager | None = credential_pool_manager,
    ):
        configured_providers = (
            (
                OpenAIProvider(),
                AnthropicProvider(),
                GeminiProvider(),
                GroqProvider(),
                OllamaProvider(),
                *build_openai_compatible_providers(),
            )
            if providers is None
            else providers
        )
        self._providers = {
            provider.spec.provider_id: provider for provider in configured_providers
        }
        self._credential_pool = credential_pool

    def get(self, provider_id: str) -> AIProvider:
        normalized = provider_id.strip().lower()
        try:
            return self._providers[normalized]
        except KeyError:
            raise UnsupportedProviderError(
                normalized or "unknown",
                "Configured provider is not supported",
            ) from None

    def catalog(self) -> list[dict[str, str | bool]]:
        """Return public provider metadata without configuration or credentials."""
        return [
            provider.spec.catalog_entry()
            for provider in self._providers.values()
        ]

    async def generate_with_provider(
        self,
        provider_id: str,
        model: str,
        role: str,
        prompt: str,
        configuration: Settings | None = None,
        *,
        attachments: tuple[ProviderAttachment, ...] = (),
    ) -> ProviderDispatchResult:
        """Dispatch to one explicit provider without an online fallback."""
        active_settings = configuration or settings
        try:
            provider = self.get(provider_id)
            request = ProviderRequest(
                prompt=prompt,
                model=model,
                timeout_seconds=active_settings.provider_timeout(provider_id),
                role=role,
                attachments=attachments,
            )
            result = await self._invoke(provider, request, active_settings)
        except ProviderError as error:
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata={"provider": provider_id, "model": model, "fallback_used": False},
            )
        metadata: dict[str, object] = {
            "provider": provider_id, "model": model, "fallback_used": False
        }
        metadata.update({
            key: result.metadata[key]
            for key in ("response_type", "finish_reason", "reasoning_effort")
            if key in result.metadata
        })
        return ProviderDispatchResult(result=result.response_payload(), metadata=metadata)

    @staticmethod
    def _legacy_credential_for(
        configuration: Settings,
        provider: AIProvider,
    ) -> ProviderCredential | None:
        if not provider.spec.requires_api_key:
            return None
        value = configuration.provider_api_key(provider.spec.provider_id)
        if not value:
            return None
        return ProviderCredential(
            provider_id=provider.spec.provider_id,
            secret=value,
        )

    @staticmethod
    def _error_result(error: ProviderError) -> dict[str, object]:
        status = (
            "not_configured"
            if isinstance(error, ProviderConfigurationError)
            else "error"
        )
        return {
            "status": status,
            "message": str(error),
            "error_code": error.code,
        }

    async def _invoke(
        self,
        provider: AIProvider,
        request: ProviderRequest,
        configuration: Settings,
    ):
        if not provider.spec.requires_api_key:
            return await provider.generate(request, None)

        pool = self._credential_pool
        try:
            has_pool_credentials = (
                pool is not None
                and pool.has_credentials(provider.spec.provider_id)
            )
        except (CredentialPoolError, sqlite3.Error, OSError):
            raise ProviderUnavailableError(
                provider.spec.provider_id,
                "Provider credential pool is unavailable",
                reason="pool_unavailable",
            ) from None
        if not has_pool_credentials:
            credential = self._legacy_credential_for(configuration, provider)
            return await provider.generate(request, credential)

        attempts = 0
        while attempts < configuration.CREDENTIAL_POOL_MAX_ATTEMPTS:
            try:
                lease = await pool.acquire(provider.spec.provider_id)
            except (CredentialPoolError, sqlite3.Error, OSError):
                raise ProviderUnavailableError(
                    provider.spec.provider_id,
                    "Provider credential pool is unavailable",
                    reason="pool_unavailable",
                ) from None
            if lease is None:
                break

            attempts += 1
            try:
                result = await provider.generate(request, lease.credential)
            except ProviderUnavailableError as error:
                try:
                    pool.record_failure(
                        lease.credential_id,
                        error.reason,
                        retry_after_seconds=error.retry_after_seconds,
                    )
                except (CredentialPoolError, sqlite3.Error, OSError):
                    raise ProviderUnavailableError(
                        provider.spec.provider_id,
                        "Provider credential pool is unavailable",
                        reason="pool_unavailable",
                    ) from None
                continue
            except (ProviderConfigurationError, ProviderResponseError):
                raise
            else:
                try:
                    pool.record_success(lease.credential_id)
                except (CredentialPoolError, sqlite3.Error, OSError):
                    raise ProviderUnavailableError(
                        provider.spec.provider_id,
                        "Provider credential pool is unavailable",
                        reason="pool_unavailable",
                    ) from None
                return result

        raise ProviderUnavailableError(
            provider.spec.provider_id,
            "Provider credential pool is unavailable",
            reason="pool_exhausted",
        )

    async def generate_for_role(
        self,
        role: str,
        prompt: str,
        configuration: Settings | None = None,
        *,
        response_schema: dict[str, object] | None = None,
        response_schema_name: str = "structured_response",
        attachments: tuple[ProviderAttachment, ...] = (),
    ) -> ProviderDispatchResult:
        """Generate through a role's provider and one explicit fallback at most."""
        active_settings = configuration or settings
        try:
            role_settings = active_settings.role_provider_settings(role)
            primary = self.get(role_settings.provider)
        except SettingsValidationError as error:
            provider_error = ProviderConfigurationError("registry", str(error))
            return ProviderDispatchResult(
                result=self._error_result(provider_error),
                metadata={"provider": "", "model": "", "fallback_used": False},
            )
        except UnsupportedProviderError as error:
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata={
                    "provider": error.provider_id,
                    "model": role_settings.model,
                    "fallback_used": False,
                },
            )

        if role_settings.fallback_provider == primary.spec.provider_id:
            error = ProviderConfigurationError(
                primary.spec.provider_id,
                "Primary and fallback providers must differ",
            )
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata={
                    "provider": primary.spec.provider_id,
                    "model": role_settings.model,
                    "fallback_used": False,
                },
            )

        primary_request = ProviderRequest(
            prompt=prompt,
            model=role_settings.model,
            timeout_seconds=active_settings.provider_timeout(
                primary.spec.provider_id
            ),
            role=role,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            attachments=attachments,
            reasoning_effort=role_settings.reasoning_effort,
        )
        primary_metadata: dict[str, object] = {
            "provider": primary.spec.provider_id,
            "model": primary_request.model,
            "fallback_used": False,
        }

        try:
            result = await self._invoke(primary, primary_request, active_settings)
            primary_metadata.update({
                key: result.metadata[key]
                for key in ("response_type", "finish_reason", "reasoning_effort")
                if key in result.metadata
            })
            return ProviderDispatchResult(
                result=result.response_payload(),
                metadata=primary_metadata,
            )
        except (ProviderConfigurationError, ProviderResponseError) as error:
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata=primary_metadata,
            )
        except UnsupportedProviderError as error:
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata=primary_metadata,
            )
        except ProviderUnavailableError as primary_error:
            if not role_settings.fallback_provider:
                return ProviderDispatchResult(
                    result=self._error_result(primary_error),
                    metadata=primary_metadata,
                )

        try:
            fallback = self.get(role_settings.fallback_provider)
        except UnsupportedProviderError as error:
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata=primary_metadata,
            )

        if fallback.spec.provider_id == primary.spec.provider_id:
            error = ProviderConfigurationError(
                primary.spec.provider_id,
                "Primary and fallback providers must differ",
            )
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata=primary_metadata,
            )

        fallback_request = ProviderRequest(
            prompt=prompt,
            model=fallback.spec.default_model,
            timeout_seconds=active_settings.provider_timeout(
                fallback.spec.provider_id
            ),
            role=role,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            attachments=attachments,
        )
        fallback_metadata: dict[str, object] = {
            "provider": fallback.spec.provider_id,
            "model": fallback_request.model,
            "fallback_used": True,
        }

        try:
            result = await self._invoke(
                fallback,
                fallback_request,
                active_settings,
            )
            fallback_metadata.update({
                key: result.metadata[key]
                for key in ("response_type", "finish_reason", "reasoning_effort")
                if key in result.metadata
            })
            return ProviderDispatchResult(
                result=result.response_payload(),
                metadata=fallback_metadata,
            )
        except ProviderError:
            error = ProviderUnavailableError(
                fallback.spec.provider_id,
                "Primary and fallback providers are unavailable",
                reason="fallback_failed",
            )
            return ProviderDispatchResult(
                result=self._error_result(error),
                metadata=fallback_metadata,
            )


    async def stream_for_role(
        self,
        role: str,
        prompt: str,
        configuration: Settings | None = None,
        *,
        response_schema: dict[str, object] | None = None,
        response_schema_name: str = "structured_response",
    ):
        """Stream a role's primary provider token-by-token.

        Yields the provider's streaming events ({"type": "delta"|"final", ...}).
        Streaming has no online fallback: if the primary provider does not
        implement it, a ProviderConfigurationError with code
        `streaming_unsupported` is raised so the caller can fall back to the
        non-streaming path. Credentials are resolved through the same pool /
        legacy path as `_invoke`, but without cross-lease retries.
        """
        active_settings = configuration or settings
        role_settings = active_settings.role_provider_settings(role)
        primary = self.get(role_settings.provider)
        stream_fn = getattr(primary, "generate_stream", None)
        if stream_fn is None:
            raise ProviderConfigurationError(
                primary.spec.provider_id, "streaming_unsupported"
            )
        request = ProviderRequest(
            prompt=prompt,
            model=role_settings.model,
            timeout_seconds=active_settings.provider_timeout(primary.spec.provider_id),
            role=role,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            reasoning_effort=role_settings.reasoning_effort,
        )

        credential: ProviderCredential | None = None
        lease = None
        pool = self._credential_pool
        if primary.spec.requires_api_key:
            try:
                use_pool = pool is not None and pool.has_credentials(
                    primary.spec.provider_id
                )
            except (CredentialPoolError, sqlite3.Error, OSError):
                raise ProviderUnavailableError(
                    primary.spec.provider_id,
                    "Provider credential pool is unavailable",
                    reason="pool_unavailable",
                ) from None
            if use_pool:
                try:
                    lease = await pool.acquire(primary.spec.provider_id)
                except (CredentialPoolError, sqlite3.Error, OSError):
                    raise ProviderUnavailableError(
                        primary.spec.provider_id,
                        "Provider credential pool is unavailable",
                        reason="pool_unavailable",
                    ) from None
                if lease is None:
                    raise ProviderUnavailableError(
                        primary.spec.provider_id,
                        "Provider credential pool is unavailable",
                        reason="pool_exhausted",
                    )
                credential = lease.credential
            else:
                credential = self._legacy_credential_for(active_settings, primary)

        try:
            async for event in stream_fn(request, credential):
                yield event
        except ProviderUnavailableError as error:
            if lease is not None:
                try:
                    pool.record_failure(
                        lease.credential_id,
                        error.reason,
                        retry_after_seconds=error.retry_after_seconds,
                    )
                except (CredentialPoolError, sqlite3.Error, OSError):
                    pass
            raise
        else:
            if lease is not None:
                try:
                    pool.record_success(lease.credential_id)
                except (CredentialPoolError, sqlite3.Error, OSError):
                    pass


    async def _acquire_single_credential(self, provider, configuration):
        """Acquire one credential (pool lease or legacy) for a single dispatch.

        Returns (credential, lease). Raises ProviderUnavailableError on pool
        issues. Used by the streaming and agentic paths, which do not retry
        across leases the way `_invoke` does.
        """
        if not provider.spec.requires_api_key:
            return None, None
        pool = self._credential_pool
        try:
            use_pool = pool is not None and pool.has_credentials(
                provider.spec.provider_id
            )
        except (CredentialPoolError, sqlite3.Error, OSError):
            raise ProviderUnavailableError(
                provider.spec.provider_id,
                "Provider credential pool is unavailable",
                reason="pool_unavailable",
            ) from None
        if use_pool:
            try:
                lease = await pool.acquire(provider.spec.provider_id)
            except (CredentialPoolError, sqlite3.Error, OSError):
                raise ProviderUnavailableError(
                    provider.spec.provider_id,
                    "Provider credential pool is unavailable",
                    reason="pool_unavailable",
                ) from None
            if lease is None:
                raise ProviderUnavailableError(
                    provider.spec.provider_id,
                    "Provider credential pool is unavailable",
                    reason="pool_exhausted",
                )
            return lease.credential, lease
        return self._legacy_credential_for(configuration, provider), None

    async def agentic_for_role(
        self,
        role: str,
        prompt: str,
        tool_executor,
        configuration: Settings | None = None,
        *,
        tools: list,
        response_schema: dict[str, object] | None = None,
        response_schema_name: str = "structured_response",
        max_rounds: int = 6,
    ):
        """Run a bounded tool-calling loop for a role's primary provider.

        The model may call the read-only tools passed in `tools`, executed by
        the sync `tool_executor(name, arguments_dict) -> str` callback (which
        must never raise and never mutate). Yields `tool_call` / `tool_result`
        events as they happen and a terminal `final` event carrying the model's
        structured text. If the primary provider cannot tool-call, raises a
        ProviderConfigurationError with code `tools_unsupported` so the caller
        can fall back to the non-agentic path.
        """
        active_settings = configuration or settings
        role_settings = active_settings.role_provider_settings(role)
        primary = self.get(role_settings.provider)
        respond = getattr(primary, "respond_with_tools", None)
        if respond is None:
            raise ProviderConfigurationError(
                primary.spec.provider_id, "tools_unsupported"
            )
        request = ProviderRequest(
            prompt=prompt,
            model=role_settings.model,
            timeout_seconds=active_settings.provider_timeout(primary.spec.provider_id),
            role=role,
            response_schema=response_schema,
            response_schema_name=response_schema_name,
            reasoning_effort=role_settings.reasoning_effort,
        )
        credential, lease = await self._acquire_single_credential(
            primary, active_settings
        )
        success = False
        try:
            input_items: list = [{"role": "user", "content": prompt}]
            for _ in range(max_rounds):
                result = await respond(
                    request, credential, input_items=input_items, tools=tools
                )
                calls = result.get("function_calls") or []
                if calls:
                    for call in calls:
                        name = call.get("name") or ""
                        call_id = call.get("call_id")
                        raw_args = call.get("arguments")
                        args_text = raw_args if isinstance(raw_args, str) else "{}"
                        yield {"type": "tool_call", "name": name, "arguments": args_text}
                        try:
                            parsed = json.loads(args_text) if args_text.strip() else {}
                            if not isinstance(parsed, dict):
                                parsed = {}
                        except json.JSONDecodeError:
                            parsed = {}
                        output = await asyncio.to_thread(tool_executor, name, parsed)
                        yield {"type": "tool_result", "name": name}
                        input_items.append({
                            "type": "function_call",
                            "call_id": call_id,
                            "name": name,
                            "arguments": args_text,
                        })
                        input_items.append({
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": output,
                        })
                    continue
                text = result.get("output_text")
                if text:
                    success = True
                    yield {
                        "type": "final",
                        "text": text,
                        "metadata": {
                            "finish_reason": result.get("status"),
                            "reasoning_effort": role_settings.reasoning_effort,
                        },
                    }
                    return
                raise ProviderResponseError(
                    primary.spec.provider_id, "Provider returned no output"
                )
            raise ProviderResponseError(
                primary.spec.provider_id, "Tool loop did not converge"
            )
        except ProviderUnavailableError as error:
            if lease is not None:
                try:
                    self._credential_pool.record_failure(
                        lease.credential_id,
                        error.reason,
                        retry_after_seconds=error.retry_after_seconds,
                    )
                except (CredentialPoolError, sqlite3.Error, OSError):
                    pass
            raise
        finally:
            if lease is not None and success:
                try:
                    self._credential_pool.record_success(lease.credential_id)
                except (CredentialPoolError, sqlite3.Error, OSError):
                    pass


provider_registry = ProviderRegistry()
