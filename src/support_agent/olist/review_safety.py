"""Offline review risk assessment. No comment text is returned, logged or stored.

Pattern redaction does not establish Portuguese names/address privacy coverage.
Comments remain excluded from import, retrieval, citations and customer output.
"""

from support_agent.guardrails.injection import quarantine_tool_output
from support_agent.guardrails.pii import get_redactor


def assess_comment(text: str) -> dict:
    redactor = get_redactor()
    redacted = redactor.redact(text).text
    quarantined = quarantine_tool_output("historical_customer_feedback", redacted)
    return {
        "source_kind": "untrusted_customer_feedback",
        "input_utf8_bytes": len(text.encode("utf-8")),
        "redacted_utf8_bytes": len(redacted.encode("utf-8")),
        "pii_detected": redacted != text,
        "instruction_attempt": quarantined.triggered,
        "presidio_available": bool(redactor._presidio),
        "publishable": False,
        "reason": "Portuguese PII coverage requires validation; raw and redacted comments are withheld.",
    }
