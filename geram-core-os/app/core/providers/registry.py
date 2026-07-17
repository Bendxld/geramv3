"""Provider registry and role-aware primary/fallback dispatch."""

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
    ProviderResponseError,
    ProviderUnavailableError,
    UnsupportedProviderError,
)
from app.core.providers.gemini_client import GeminiProvider
from app.core.providers.groq_client import GroqProvider
from app.core.providers.openai_client import OpenAIProvider
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
                GeminiProvider(),
                GroqProvider(),
                OllamaProvider(),
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
                for key in ("response_type", "finish_reason")
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
                for key in ("response_type", "finish_reason")
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


provider_registry = ProviderRegistry()
