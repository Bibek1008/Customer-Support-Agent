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

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from support_agent.observability.tracing import guardrail_span

_LOGGER = logging.getLogger(__name__)

# High-precision fallback patterns, used only when Presidio is unavailable.
_FALLBACK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL_ADDRESS", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE_NUMBER", re.compile(r"\b(?:\+?\d{1,3}[ -]?)?(?:\(?\d{3}\)?[ -]?)\d{3}[ -]?\d{4}\b")),
    ("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]
_SSN_AREA = r"(?!000|666|9\d\d)\d{3}"
_SSN_GROUP = r"(?!00)\d{2}"
_SSN_SERIAL = r"(?!0000)\d{4}"
_SSN_GROUPS = rf"{_SSN_AREA}{_SSN_GROUP}{_SSN_SERIAL}"
_FORMATTED_SSN = re.compile(
    rf"(?<!\d){_SSN_AREA}(?P<separator>[- ]){_SSN_GROUP}"
    rf"(?P=separator){_SSN_SERIAL}(?!\d)"
)
_CONTEXTUAL_SSN = re.compile(
    rf"(?P<context>\b(?:ssn|social\s+security(?:\s+number)?)\b"
    rf"[^0-9]{{0,24}})(?P<ssn>(?<!\d){_SSN_GROUPS}(?!\d))",
    flags=re.IGNORECASE,
)
_NON_PII_DURATION = re.compile(
    r"(?<!\w)(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"[ -]+(?:business[ -]+)?(?:minutes?|hours?|days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
_BUSINESS_ID_PREFIX = re.compile(
    r"\b(?:order|ticket|case|reference|ref|invoice|tracking|confirmation|transaction)"
    r"\s*(?:(?:number|no\.?|id|reference)\s*)?[:#-]?\s*$",
    re.IGNORECASE,
)
_AMBIGUOUS_NUMERIC_ENTITIES = {
    "DATE_TIME",
    "US_BANK_NUMBER",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
}
_INTERNAL_TICKET_ID = re.compile(r"\btkt_[a-f0-9]{12}\b")


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
        except Exception as exc:  # noqa: BLE001 - detector setup must fall back safely
            _LOGGER.warning(
                "Presidio initialization failed; regex PII fallback is active (%s).",
                type(exc).__name__,
            )
            return False

    def redact(self, text: str) -> RedactionResult:
        """Return the text with PII replaced by typed placeholders."""
        if not text:
            return RedactionResult(text=text, entities=[])
        with guardrail_span("pii") as span:
            ssn_result = self._redact_ssn(text)
            try:
                result = (
                    self._redact_presidio(ssn_result.text)
                    if self._presidio
                    else self._redact_regex(ssn_result.text)
                )
            except Exception as exc:  # noqa: BLE001 - detector failure must not fail open
                # Detector exceptions can include input text; log only the type.
                _LOGGER.warning(
                    "Presidio redaction failed; using regex fallback (%s).",
                    type(exc).__name__,
                )
                result = self._redact_regex(ssn_result.text)
            result.entities = list(dict.fromkeys(ssn_result.entities + result.entities))
            span.set("guardrail.pii.entities", ",".join(sorted(set(result.entities))))
            span.set("guardrail.pii.had_pii", result.had_pii)
            return result

    def _redact_presidio(self, text: str) -> RedactionResult:
        from presidio_anonymizer.entities import OperatorConfig

        # Presidio debug logs can include the analyzed text; never emit it.
        for logger_name in ("presidio", "presidio-analyzer", "presidio-anonymizer"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        results = self._analyzer.analyze(text=text, language="en")
        results = [
            result
            for result in results
            if not self._is_known_false_positive(
                text,
                result.entity_type,
                result.start,
                result.end,
            )
        ]
        entities = [r.entity_type for r in results]
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            # Replace with a typed placeholder, e.g. <EMAIL_ADDRESS>.
            operators={"DEFAULT": OperatorConfig("replace", {"new_value": None})},
        )
        return RedactionResult(text=anonymized.text, entities=entities)

    @staticmethod
    def _is_known_false_positive(
        text: str,
        entity_type: str,
        start: int,
        end: int,
    ) -> bool:
        if any(
            match.start() <= start and end <= match.end()
            for match in _INTERNAL_TICKET_ID.finditer(text)
        ):
            return True
        candidate = text[start:end]
        if entity_type == "DATE_TIME" and _NON_PII_DURATION.fullmatch(candidate):
            return True
        prefix = text[max(0, start - 48) : start]
        return (
            entity_type in _AMBIGUOUS_NUMERIC_ENTITIES
            and candidate.isdigit()
            and len(candidate) == 9
            and bool(_BUSINESS_ID_PREFIX.search(prefix))
        )

    def _redact_ssn(self, text: str) -> RedactionResult:
        """Catch SSNs Presidio's default English registry does not recognize."""
        entities: list[str] = []
        redacted = _FORMATTED_SSN.sub("<US_SSN>", text)
        if redacted != text:
            entities.append("US_SSN")

        contextual = _CONTEXTUAL_SSN.sub(
            lambda match: f"{match.group('context')}<US_SSN>",
            redacted,
        )
        if contextual != redacted:
            entities.append("US_SSN")
        return RedactionResult(
            text=contextual,
            entities=list(dict.fromkeys(entities)),
        )

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
