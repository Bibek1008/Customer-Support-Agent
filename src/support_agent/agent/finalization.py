"""Canonical customer content: sanitize, validate, then seal against later mutation."""

import json
import re
from copy import deepcopy

from support_agent.guardrails.pii import get_redactor
from support_agent.guardrails.redaction import public_document_url, redact_secrets
from support_agent.schemas import ChatResponse, Citation, Decision, DecisionType, Trace


class FinalizationError(RuntimeError):
    """Customer content was not validated, or changed after validation."""


def sanitize_citations(citations: list[Citation]) -> list[Citation]:
    redactor = get_redactor()
    result = []
    for citation in citations:
        approved = citation._approved_kb
        url = citation.url
        # A model/client cannot grant provenance by supplying a JSON field.
        keep_url = approved and public_document_url(url) and redact_secrets(url) == url
        source_id = citation.source_id
        # Approved document slugs are identifiers, not arbitrary free text. Still
        # apply deterministic PII/secret rules before preserving detector-noisy IDs.
        safe_id = (
            approved
            and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_/-]{0,79}", source_id)
            and redactor._redact_regex(redactor._redact_ssn(source_id).text).text == source_id
        )
        result.append(
            citation.model_copy(
                update={
                    "source_id": source_id if safe_id else redactor.redact(source_id).text,
                    "source_title": redactor.redact(citation.source_title).text,
                    "url": url if keep_url else None,
                    "chunk": redactor.redact(citation.chunk, approved_policy=approved).text,
                }
            )
        )
    return result


def prepare_decision(decision: Decision) -> Decision:
    """All customer-facing text transformations happen before evaluation."""
    citations = sanitize_citations(decision.citations)
    approved_policy = any(c._approved_kb for c in citations)
    return decision.model_copy(
        update={
            "answer": get_redactor()
            .redact(decision.answer or "", approved_policy=approved_policy)
            .text,
            "citations": citations,
            "handoff_reason": get_redactor().redact(decision.handoff_reason).text
            if decision.handoff_reason
            else None,
        }
    )


def customer_content(decision: Decision) -> dict:
    return {
        "answer": decision.answer or "",
        "citations": [c.model_dump(mode="json") for c in decision.citations],
        "ticket_id": decision.ticket_id,
        "decision": decision.type.value,
        "handoff": decision.type == DecisionType.HANDOFF,
    }


def content_signature(decision: Decision) -> str:
    return json.dumps(customer_content(decision), sort_keys=True, ensure_ascii=False)


def prepare_response(trace: Trace, decision: Decision) -> None:
    """Construct the full response before evaluating any customer content.

    Only evaluation results, tracing IDs and cost accounting are filled in later.
    They must never change the already constructed answer, sources or ticket ID.
    """
    from support_agent.request_context import current_request

    context = current_request.get()
    trace._canonical_response = ChatResponse(
        conversation_id=trace.conversation_id,
        request_id=context.request_id if context else None,
        langfuse_trace_id=trace.langfuse_trace_id,
        decision=decision.type,
        answer=decision.answer or "",
        confidence=decision.confidence,
        threshold=decision.threshold,
        handoff=decision.type == DecisionType.HANDOFF,
        ticket_id=decision.ticket_id,
        citations=[c.model_copy(deep=True) for c in decision.citations],
        cost_usd=trace.total_usd(),
    )


def _matches_canonical(trace: Trace, decision: Decision) -> bool:
    if trace._canonical_response is None:
        return False
    payload = trace._canonical_response.model_dump(mode="json")
    return all(payload[key] == value for key, value in customer_content(decision).items())


def seal_decision(trace: Trace, decision: Decision) -> Decision:
    if not _matches_canonical(trace, decision):
        raise FinalizationError("Customer content changed after response construction.")
    trace._validated_content = content_signature(decision)
    trace.decision = decision
    return decision


def assert_finalized(trace: Trace) -> None:
    if (
        trace.decision is None
        or trace._validated_content is None
        or trace._validated_content != content_signature(trace.decision)
        or not _matches_canonical(trace, trace.decision)
    ):
        raise FinalizationError("Customer content must be validated again after any change.")


def citation_safety_text(decision: Decision) -> str:
    """Sources are customer-visible too; check their complete displayed content."""
    return "\n\n".join(
        f"{c.source_id}\n{c.source_title}\n{c.chunk}\n{c.url or ''}" for c in decision.citations
    )


class FinalPayload(dict):
    """API JSON with a mutation check used by the persistence boundary."""

    def __init__(self, value: dict):
        super().__init__(deepcopy(value))
        self._snapshot = json.dumps(self, sort_keys=True, ensure_ascii=False)

    def verified_copy(self) -> dict:
        if json.dumps(self, sort_keys=True, ensure_ascii=False) != self._snapshot:
            raise FinalizationError("Final API payload changed after serialization.")
        return deepcopy(dict(self))


def response_payload(
    trace: Trace, *, request_id: str | None = None, cost_usd: float | None = None
) -> FinalPayload:
    """Attach non-content request/cost/evaluation metadata to validated content."""
    assert_finalized(trace)
    decision = trace.decision
    response = trace._canonical_response.model_copy(
        update={
            "request_id": request_id,
            "langfuse_trace_id": trace.langfuse_trace_id,
            "confidence": decision.confidence,
            "threshold": decision.threshold,
            "cost_usd": trace.total_usd() if cost_usd is None else cost_usd,
        }
    ).model_dump(mode="json")
    if any(response[key] != value for key, value in customer_content(decision).items()):
        raise FinalizationError("API serialization changed validated customer content.")
    return FinalPayload(response)
