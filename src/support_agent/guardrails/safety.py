"""Safety classification with Llama Guard 4.

Llama Guard 4 (12B, pruned from Llama 4 Scout) classifies both the input prompt
and the model response against the MLCommons hazards taxonomy. We call it through
an OpenAI-compatible model server (vLLM/TGI); the model is the only thing on our
side that needs a GPU (FACTS.md Section 4). On a 24 GB card run it quantized
(FP8/INT8); on a 48 GB card it fits in BF16 with headroom.

The classifier returns "safe" or "unsafe" plus the violated category codes. When
no safety server is configured we return a benign, clearly-labelled result and
record it on the span, so local development is not blocked. A deployment must
point ``SAFETY_MODEL_URL`` at a real server.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import httpx

from support_agent.config import get_settings
from support_agent.observability.tracing import guardrail_span


class SafetyRole(str, Enum):
    """Which side of the exchange is being classified."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class SafetyVerdict:
    safe: bool
    categories: list[str]  # e.g. ["S1"] hazard codes when unsafe
    checked: bool  # False when no safety server was available

    @property
    def blocked(self) -> bool:
        return self.checked and not self.safe


class SafetyClassifier:
    """Classify prompts and responses with Llama Guard 4."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def classify(self, text: str, role: SafetyRole) -> SafetyVerdict:
        with guardrail_span("safety") as span:
            span.set("guardrail.safety.role", role.value)
            if not self.settings.safety_model_url:
                # Fail-open-and-log for local dev; a deployment must set the URL.
                span.set("guardrail.safety.checked", False)
                return SafetyVerdict(safe=True, categories=[], checked=False)
            verdict = self._call_server(text, role)
            span.set("guardrail.safety.safe", verdict.safe)
            span.set("guardrail.safety.categories", ",".join(verdict.categories))
            span.set("guardrail.safety.checked", True)
            return verdict

    def _call_server(self, text: str, role: SafetyRole) -> SafetyVerdict:
        # Llama Guard expects the turn to classify wrapped as a chat message; the
        # server applies the Guard prompt template and returns a short verdict.
        messages = [{"role": role.value, "content": text}]
        try:
            resp = httpx.post(
                f"{self.settings.safety_model_url.rstrip('/')}/chat/completions",
                json={
                    "model": self.settings.safety_model_name,
                    "messages": messages,
                    "max_tokens": 32,
                    "temperature": 0.0,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception:
            # A safety server that is down must not silently pass unsafe content.
            # Treat an outage as "unknown, block" for the assistant side and
            # "unknown, allow-with-flag" for the user side; here we conservatively
            # mark unchecked so the caller can decide. We choose to block.
            return SafetyVerdict(safe=False, categories=["UNAVAILABLE"], checked=True)
        return self._parse(content)

    @staticmethod
    def _parse(content: str) -> SafetyVerdict:
        """Llama Guard replies with 'safe' or 'unsafe\\nS1,S3' style output."""
        lines = [ln.strip() for ln in content.strip().splitlines() if ln.strip()]
        if not lines:
            return SafetyVerdict(safe=True, categories=[], checked=True)
        first = lines[0].lower()
        if first.startswith("safe"):
            return SafetyVerdict(safe=True, categories=[], checked=True)
        categories: list[str] = []
        if len(lines) > 1:
            categories = [c.strip() for c in lines[1].replace(" ", "").split(",") if c.strip()]
        return SafetyVerdict(safe=False, categories=categories, checked=True)


_CLASSIFIER: SafetyClassifier | None = None


def get_classifier() -> SafetyClassifier:
    global _CLASSIFIER
    if _CLASSIFIER is None:
        _CLASSIFIER = SafetyClassifier()
    return _CLASSIFIER
