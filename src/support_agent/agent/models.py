"""Model routing and the Anthropic client.

Three roles, three models, IDs pinned in ``FACTS.md`` Section 1:

- the primary reasoner (Claude Opus 4.8) drives the tool-use loop,
- a cost-efficient tier (Claude Sonnet 5) is available for high-volume routing,
- a cheap classifier (Claude Haiku 4.5) scores confidence and tone.

FACTS.md fixes the API surface we build against: thinking is adaptive only
(``budget_tokens`` and sampling parameters return 400), depth is set with
``output_config.effort``, and structured JSON is forced with
``output_config.format`` rather than an assistant prefill. This module centralizes
those choices so every call obeys them.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from support_agent.config import get_settings

try:
    import anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:  # pragma: no cover - the SDK may be absent in a bare test env
    _ANTHROPIC_AVAILABLE = False


@lru_cache
def get_client():
    """Return the configured provider's client; credentials come from settings."""
    settings = get_settings()
    if settings.llm_provider == "groq":
        from support_agent.agent.groq_client import GroqClient

        return GroqClient(settings.groq_api_key)
    if not _ANTHROPIC_AVAILABLE:
        raise RuntimeError(
            "The 'anthropic' package is not installed. Install dependencies to "
            "run the agent loop."
        )
    # The SDK falls back to ANTHROPIC_API_KEY in the environment; we pass ours
    # explicitly only when it is set, so a profile-based login still works.
    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return anthropic.Anthropic()


def reasoner_kwargs() -> dict[str, Any]:
    """Base request kwargs for the primary reasoner (Opus 4.8).

    Adaptive thinking on, depth via effort. No ``budget_tokens`` and no
    ``temperature``; both return 400 on this model.
    """
    settings = get_settings()
    if settings.llm_provider == "groq":
        return {"model": settings.groq_model, "max_tokens": min(settings.max_output_tokens, 2048)}
    return {
        "model": settings.agent_model,
        "max_tokens": settings.max_output_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": settings.agent_effort},
    }


def classifier_kwargs() -> dict[str, Any]:
    """Base request kwargs for the cheap classifier (Haiku 4.5).

    Used for the confidence score and the tone judge. Small output, structured.
    """
    settings = get_settings()
    if settings.llm_provider == "groq":
        return {"model": settings.groq_model, "max_tokens": 2048}
    return {
        "model": settings.classifier_model,
        "max_tokens": 512,
    }
