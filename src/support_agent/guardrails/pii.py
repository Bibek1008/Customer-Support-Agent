"""PII redaction with Microsoft Presidio.

We redact PII on the way in (before the model or the logs ever see it) and again
before anything is persisted. Presidio's Analyzer finds the entities and the
Anonymizer replaces them with typed placeholders, so ``jane@acme.com`` becomes
``<EMAIL_ADDRESS>`` and a card number becomes ``<CREDIT_CARD>``. The placeholder
keeps the sentence readable for the model without carrying the raw value.

Presidio is MIT-licensed. When it is not installed (or its spaCy model is
missing), we fall back to a small set of high-precision regexes so the guardrail
still redacts the obvious identifiers rather than failing open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from support_agent.observability.tracing import guardrail_span

# High-precision fallback patterns, used only when Presidio is unavailable.
_FALLBACK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL_ADDRESS", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE_NUMBER", re.compile(r"\b(?:\+?\d{1,3}[ -]?)?(?:\(?\d{3}\)?[ -]?)\d{3}[ -]?\d{4}\b")),
    ("US_SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


@dataclass
class RedactionResult:
    text: str
    entities: list[str]  # entity types that were redacted, e.g. ["EMAIL_ADDRESS"]

    @property
    def had_pii(self) -> bool:
        return bool(self.entities)


class PIIRedactor:
    """Redact PII from free text. One instance per process."""

    def __init__(self) -> None:
        self._analyzer = None
        self._anonymizer = None
        self._presidio = self._try_load_presidio()

    def _try_load_presidio(self) -> bool:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine

            self._analyzer = AnalyzerEngine()
            self._anonymizer = AnonymizerEngine()
            return True
        except Exception:
            return False

    def redact(self, text: str) -> RedactionResult:
        """Return the text with PII replaced by typed placeholders."""
        if not text:
            return RedactionResult(text=text, entities=[])
        with guardrail_span("pii") as span:
            result = self._redact_presidio(text) if self._presidio else self._redact_regex(text)
            span.set("guardrail.pii.entities", ",".join(sorted(set(result.entities))))
            span.set("guardrail.pii.had_pii", result.had_pii)
            return result

    def _redact_presidio(self, text: str) -> RedactionResult:
        from presidio_anonymizer.entities import OperatorConfig

        results = self._analyzer.analyze(text=text, language="en")
        entities = [r.entity_type for r in results]
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            # Replace with a typed placeholder, e.g. <EMAIL_ADDRESS>.
            operators={
                "DEFAULT": OperatorConfig(
                    "replace", {"new_value": None}
                )
            },
        )
        return RedactionResult(text=anonymized.text, entities=entities)

    def _redact_regex(self, text: str) -> RedactionResult:
        entities: list[str] = []
        redacted = text
        for label, pattern in _FALLBACK_PATTERNS:
            if pattern.search(redacted):
                entities.append(label)
                redacted = pattern.sub(f"<{label}>", redacted)
        return RedactionResult(text=redacted, entities=entities)


@lru_cache
def get_redactor() -> PIIRedactor:
    return PIIRedactor()
