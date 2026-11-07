"""Retry a single rate-limited inference call; never replay a turn or a tool."""

import time

from support_agent.agent.groq_client import GeminiClient, GroqClient, GroqRequestError
from support_agent.config import get_settings
from support_agent.observability.tracing import guardrail_span


class QuotaFallbackClient:
    def __init__(self, primary: GroqClient, secondary: GeminiClient):
        self.primary = primary
        self.secondary = secondary
        self.messages = self
        self._retry_primary_after = 0.0

    def create(self, **kwargs):
        if time.monotonic() >= self._retry_primary_after:
            try:
                return self.primary.messages.create(**kwargs)
            except GroqRequestError as error:
                if error.status_code != 429:
                    raise
                # A bounded per-process cooldown avoids repeating exhausted calls.
                self._retry_primary_after = time.monotonic() + 60
        with guardrail_span("provider_fallback") as span:
            span.set("fallback.from", "groq")
            span.set("fallback.to", "gemini")
            span.set("fallback.reason", "quota")
            response = self.secondary.messages.create(
                **{**kwargs, "model": get_settings().gemini_fallback_model}
            )
            response.fallback_from = "groq"
            return response
