"""Typed, provider-agnostic contracts for text generation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    display_label: str
    default_model: str
    requires_api_key: bool = True
    implementation_available: bool = True

    def catalog_entry(self) -> dict[str, str | bool]:
        """Return only public provider metadata suitable for the config API."""
        return {
            "provider_id": self.provider_id,
            "display_label": self.display_label,
            "default_model": self.default_model,
            "requires_api_key": self.requires_api_key,
            "implementation_available": self.implementation_available,
        }


@dataclass(frozen=True)
class ProviderRequest:
    prompt: str
    model: str
    timeout_seconds: float
    role: str
    response_schema: dict[str, object] | None = None
    response_schema_name: str = "structured_response"


@dataclass(frozen=True)
class ProviderResult:
    text: str
    provider_id: str
    model: str
    metadata: dict[str, object] = field(default_factory=dict)

    def response_payload(self) -> dict[str, str]:
        """Preserve the provider-neutral result shape consumed by the HUD."""
        return {"text": self.text}


class ProviderCredential(BaseModel):
    """An explicitly revealable credential that masks every normal rendering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str
    secret: SecretStr = Field(repr=False)

    def _reveal(self) -> str:
        """Reveal the value only at the provider HTTP authorization boundary."""
        return self.secret.get_secret_value()

    def __repr__(self) -> str:
        return f"ProviderCredential(provider_id={self.provider_id!r}, secret=**********)"

    def __str__(self) -> str:
        return self.__repr__()

    def __getstate__(self):
        raise TypeError("ProviderCredential cannot be serialized with pickle")

    def __reduce_ex__(self, protocol):
        raise TypeError("ProviderCredential cannot be serialized with pickle")


class ProviderError(RuntimeError):
    """Base class for sanitized provider failures."""

    code = "provider_error"

    def __init__(self, provider_id: str, message: str):
        self.provider_id = provider_id
        super().__init__(message)


class UnsupportedProviderError(ProviderError):
    code = "unsupported_provider"


class ProviderConfigurationError(ProviderError):
    code = "provider_configuration_error"


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"

    def __init__(
        self,
        provider_id: str,
        message: str,
        *,
        reason: str,
        retry_after_seconds: float | None = None,
    ):
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        super().__init__(provider_id, message)


class ProviderResponseError(ProviderError):
    code = "provider_response_error"


class AIProvider(Protocol):
    spec: ProviderSpec

    async def generate(
        self,
        request: ProviderRequest,
        credential: ProviderCredential | None,
    ) -> ProviderResult:
        ...


def require_credential(
    spec: ProviderSpec,
    credential: ProviderCredential | None,
) -> ProviderCredential:
    """Require a non-empty credential without embedding it in any error."""
    if credential is None or not credential._reveal():
        raise ProviderConfigurationError(
            spec.provider_id,
            f"{spec.display_label} is not configured",
        )
    return credential


def parse_retry_after(value: str | None) -> float | None:
    """Parse Retry-After without retaining or exposing the raw header value."""
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    return seconds


def sanitized_http_error(
    provider_id: str,
    status_code: int,
    retry_after: str | None = None,
) -> ProviderError:
    """Classify an upstream status without exposing its body or request data."""
    if status_code in {401, 403}:
        return ProviderUnavailableError(
            provider_id,
            "Provider authentication failed",
            reason="authentication",
        )
    if status_code == 429:
        return ProviderUnavailableError(
            provider_id,
            "Provider rate limit reached",
            reason="rate_limit",
            retry_after_seconds=parse_retry_after(retry_after),
        )
    if status_code >= 500:
        return ProviderUnavailableError(
            provider_id,
            "Provider service is unavailable",
            reason="upstream",
        )
    return ProviderConfigurationError(
        provider_id,
        "Provider rejected the request or model configuration",
    )
