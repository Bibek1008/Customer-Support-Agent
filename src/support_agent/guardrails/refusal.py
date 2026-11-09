"""The refusal policy: out-of-scope, disallowed, and low-confidence paths.

Three things make the agent decline or escalate rather than answer:

1. **Disallowed**: the safety classifier flagged the input or the response, or
   the request asks for something the policy forbids (account takeover, medical
   or legal advice, anything the safety layer blocks). The agent refuses.
2. **Out of scope**: the request is not something a support agent handles
   (a general-knowledge question, a request to write code). The agent says so
   and points to the right channel.
3. **Low confidence**: the answer is in scope and allowed, but the confidence
   score is below the handoff threshold tau*. The agent escalates to a human
   rather than guess (the low-confidence handoff path, handled with
   ``agent.confidence`` and ``tools.handoff``).

This module owns safety refusal (category 1). Semantic scope routing (category 2)
lives in ``guardrails.conversation``. Category 3 lives with confidence and handoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from support_agent.config import get_settings
from support_agent.guardrails.safety import SafetyRole, SafetyUnavailableError, get_classifier
from support_agent.observability.tracing import guardrail_span


class RefusalReason(str, Enum):
    DISALLOWED = "disallowed"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass
class RefusalDecision:
    refuse: bool
    reason: RefusalReason | None = None
    message: str | None = None


# What a support agent will not do, stated plainly for the user.
_DISALLOWED_MESSAGE = (
    "I can't help with that request. If you believe this is an error, ask to be "
    "connected to a human agent and they can take a closer look."
)


def check_input(text: str) -> RefusalDecision:
    """Gate the user input before the agent loop runs."""
    with guardrail_span("refusal_input") as span:
        verdict = get_classifier().classify(text, role=SafetyRole.USER)
        if _unavailable(verdict):
            span.set("refusal.reason", "safety_unavailable")
            raise SafetyUnavailableError("Safety classification is unavailable.")
        if verdict.blocked:
            span.set("refusal.reason", RefusalReason.DISALLOWED.value)
            return RefusalDecision(
                refuse=True,
                reason=RefusalReason.DISALLOWED,
                message=_DISALLOWED_MESSAGE,
            )
        span.set("refusal.reason", "none")
        return RefusalDecision(refuse=False)


def check_response(text: str) -> RefusalDecision:
    """Gate the model's drafted answer before it reaches the user."""
    with guardrail_span("refusal_response") as span:
        verdict = get_classifier().classify(text, role=SafetyRole.ASSISTANT)
        if _unavailable(verdict):
            span.set("refusal.reason", "safety_unavailable")
            raise SafetyUnavailableError("Safety classification is unavailable.")
        if verdict.blocked:
            span.set("refusal.reason", RefusalReason.DISALLOWED.value)
            return RefusalDecision(
                refuse=True,
                reason=RefusalReason.DISALLOWED,
                message=_DISALLOWED_MESSAGE,
            )
        span.set("refusal.reason", "none")
        return RefusalDecision(refuse=False)


def _unavailable(verdict) -> bool:
    settings = get_settings()
    required = (
        settings.app_env == "production"
        or settings.safety_provider == "groq"
        or bool(settings.safety_model_url)
    )
    return any(
        category in verdict.categories for category in ("UNAVAILABLE", "INVALID_VERDICT")
    ) or (required and not verdict.checked)
