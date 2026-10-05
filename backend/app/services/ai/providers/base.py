"""Hosted model providers.

The application already supports running a quantized model locally and calling
the Hugging Face Inference API. Those two cover only open-weight checkpoints.
Popular *closed* models - ChatGPT, Claude, Gemini - are not distributed through
the Hugging Face hub at all, so each needs a provider that speaks its vendor's
API.

Every provider here implements the same interface, so `ChatModel` can dispatch
to any of them without knowing which one is active. A provider without an API
key is disabled and reports itself as such rather than failing at request time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import settings


@dataclass(frozen=True)
class HostedModel:
    """A model a provider can serve, for the in-app model selector."""

    id: str
    label: str
    provider: str
    context_length: int
    description: str = ""
    fast: bool = False
    #: Reason the model cannot be used right now, if any.
    unavailable: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "task": "text-generation",
            "context_length": self.context_length,
            "backend": self.provider,
            "description": self.description,
            "approx_size_mb": None,
            "requires_key": True,
            "configured": not self.unavailable,
            "unavailable_reason": self.unavailable,
            "fast": self.fast,
        }


@runtime_checkable
class HostedProvider(Protocol):
    """Interface implemented by every non-local generation backend."""

    name: str

    def is_configured(self) -> bool:
        """Whether an API key is present for this provider."""

    def unavailable_reason(self) -> str:
        """Human-readable reason the provider is unusable, or ""."""

    def stream(
        self,
        model_id: str,
        system: str,
        history: list[dict],
        user_message: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ):
        """Yield response text incrementally."""


class ProviderUnavailable(RuntimeError):
    """Raised when a provider is selected without the credentials it needs."""


def key_status() -> dict[str, bool]:
    """Which providers currently have credentials. Sent to the UI as booleans."""
    from app.services.ai.providers.anthropic_provider import AnthropicProvider
    from app.services.ai.providers.gemini_provider import GeminiProvider
    from app.services.ai.providers.openai_provider import OpenAIProvider

    return {
        "local": True,
        "hf_api": bool(settings.hf_token),
        "openai": OpenAIProvider().is_configured(),
        "anthropic": AnthropicProvider().is_configured(),
        "gemini": GeminiProvider().is_configured(),
    }
