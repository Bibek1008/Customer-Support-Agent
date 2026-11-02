"""The agent loop over the Claude tool runner.

One run handles one customer turn end to end:

1. Redact PII from the input, then gate it (disallowed / out of scope).
2. Run the manual tool-use loop on Claude Opus 4.8. Every tool result is passed
   through the injection quarantine before the model reads it, and the cost of
   every model call is recorded on a span.
3. When the model produces an answer, score its confidence against the sources
   it retrieved and decide handoff against tau*. Below tau*, or if the model
   itself escalated, open a human ticket instead of answering.
4. Gate the final answer with the safety classifier before returning it.

We use a manual loop rather than the SDK tool runner because two things have to
happen on every tool result (injection quarantine and per-step cost/tracing), and
the answer has to be graded for confidence before it is allowed out. Those are
cross-cutting steps the manual loop makes explicit.
"""

from __future__ import annotations

import json

from support_agent.agent.confidence import decide_handoff, score_confidence
from support_agent.agent.models import get_client, reasoner_kwargs
from support_agent.agent.prompts import SYSTEM_PROMPT
from support_agent.config import get_settings
from support_agent.guardrails import refusal
from support_agent.guardrails.injection import quarantine_tool_output
from support_agent.guardrails.pii import get_redactor
from support_agent.observability.cost import cost_from_usage
from support_agent.observability.tracing import (
    model_span,
    record_request_input,
    tool_span,
    trace_turn,
)
from support_agent.schemas import (
    Citation,
    Decision,
    DecisionType,
    Message,
    Role,
    SpanRecord,
    Trace,
)
from support_agent.tools import handoff as handoff_tool
from support_agent.tools.registry import TOOL_SCHEMAS, dispatch


@trace_turn
def run_turn(
    conversation_id: str,
    user_message: str,
    customer_id: str | None = None,
    history: list[Message] | None = None,
) -> Trace:
    """Run one customer turn through the agent and return the full trace."""
    settings = get_settings()
    trace = Trace(conversation_id=conversation_id)

    # 1. Redact PII before anything (model or logs) sees the input.
    redacted = get_redactor().redact(user_message)
    record_request_input(redacted.text)
    incoming = Message(role=Role.USER, content=redacted.text)
    prior = [
        message.model_copy(update={"content": get_redactor().redact(message.content).text})
        for message in history or []
    ]
    trace.messages = [*prior, incoming]

    # 2. Input guardrail: disallowed or out of scope -> refuse without a loop.
    gate = refusal.check_input(redacted.text)
    if gate.refuse:
        trace.decision = _refusal_decision(gate.message, settings.handoff_threshold)
        trace.messages.append(Message(role=Role.ASSISTANT, content=gate.message))
        return trace

    # 3. The manual tool-use loop.
    messages = [_anthropic_user(m) for m in trace.messages]
    citations: list[Citation] = []
    answer_text = ""
    handoff_reason: str | None = None

    for _ in range(settings.max_agent_steps):
        kwargs = reasoner_kwargs()
        with model_span(
            kwargs["model"],
            effort=kwargs.get("output_config", {}).get("effort"),
            input=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        ) as span:
            span.update(
                metadata={"tools": TOOL_SCHEMAS},
                model_parameters={
                    "max_tokens": kwargs["max_tokens"],
                    "reasoning_effort": kwargs.get("output_config", {}).get("effort", "low"),
                },
            )
            resp = get_client().messages.create(
                **kwargs,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
            cost = cost_from_usage(kwargs["model"], resp.usage)
            span.record_cost(cost)
            span.record_response(resp)
        trace.spans.append(SpanRecord(name=f"chat {kwargs['model']}", kind="model", cost=cost))

        if resp.stop_reason == "refusal":
            # The model declined for safety reasons; escalate rather than retry.
            handoff_reason = "model refused the request"
            answer_text = ""
            break

        # A server-side tool paused; resend to continue (no extra user message).
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue

        # Collect any text and any tool calls in this assistant turn.
        text_parts = [b.text for b in resp.content if b.type == "text"]
        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if resp.stop_reason == "end_turn" or not tool_uses:
            answer_text = "\n".join(text_parts).strip()
            break

        # Append the assistant turn (including tool_use blocks) before results.
        messages.append({"role": "assistant", "content": resp.content})

        # Run each tool call; return all results in one user message.
        tool_results = []
        for block in tool_uses:
            outcome = _run_tool(block, trace)
            if outcome.is_handoff:
                handoff_reason = outcome.handoff_reason
            redactor = get_redactor()
            citations.extend(
                citation.model_copy(
                    update={
                        "source_id": redactor.redact(citation.source_id).text,
                        "source_title": redactor.redact(citation.source_title).text,
                        "url": (
                            redactor.redact(citation.url).text if citation.url is not None else None
                        ),
                        "chunk": redactor.redact(citation.chunk).text,
                    }
                )
                for citation in outcome.citations
            )
            safe_tool_output = redactor.redact(outcome.text or "(no output)").text
            quarantined = quarantine_tool_output(block.name, safe_tool_output)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": quarantined.text,
                }
            )
        messages.append({"role": "user", "content": tool_results})

        if handoff_reason is not None:
            break

    # 4. Decide the outcome: answer above tau*, escalate below it or on handoff.
    trace.decision = _finalize(
        trace=trace,
        answer_text=answer_text,
        citations=_dedupe(citations),
        handoff_reason=handoff_reason,
        customer_id=customer_id,
    )
    trace.total_cost = None  # per-span costs are the source of truth
    return trace


def _run_tool(block, trace: Trace):
    """Dispatch one tool call, recording a span."""
    tool_input = block.input if isinstance(block.input, dict) else json.loads(block.input)
    with tool_span(block.name, input=tool_input) as span:
        outcome = dispatch(block.name, tool_input)
        span.update(
            output={
                "text": outcome.text,
                "citations": [c.model_dump() for c in outcome.citations],
                "handoff": outcome.is_handoff,
            }
        )
        span.set("gen_ai.tool.citations", len(outcome.citations))
        span.set("gen_ai.tool.handoff", outcome.is_handoff)
    trace.spans.append(SpanRecord(name=f"tool {block.name}", kind="tool"))
    return outcome


def _finalize(
    trace: Trace,
    answer_text: str,
    citations: list[Citation],
    handoff_reason: str | None,
    customer_id: str | None,
) -> Decision:
    settings = get_settings()
    question = next((m.content for m in reversed(trace.messages) if m.role == Role.USER), "")

    # If the model escalated, or produced no answer, hand off directly.
    if handoff_reason is not None or not answer_text:
        confidence = 0.0
        return _handoff(
            trace=trace,
            reason=handoff_reason or "the agent could not produce a grounded answer",
            confidence=confidence,
            threshold=settings.handoff_threshold,
            customer_id=customer_id,
        )

    # Score confidence against the sources actually retrieved, then apply tau*.
    conf = score_confidence(question=question, answer=answer_text, citations=citations)
    trace.spans.append(
        SpanRecord(
            name="confidence",
            kind="model",
            attributes={"score": conf.score, "reason": conf.reason},
        )
    )
    decision_hint = decide_handoff(conf.score, settings.handoff_threshold)
    if decision_hint.handoff:
        return _handoff(
            trace=trace,
            reason=decision_hint.reason,
            confidence=conf.score,
            threshold=decision_hint.threshold,
            customer_id=customer_id,
        )

    # Above tau*: gate the answer with the safety classifier, then return it.
    response_gate = refusal.check_response(answer_text)
    if response_gate.refuse:
        return _handoff(
            trace=trace,
            reason="drafted answer failed the response safety check",
            confidence=conf.score,
            threshold=decision_hint.threshold,
            customer_id=customer_id,
        )

    trace.messages.append(Message(role=Role.ASSISTANT, content=answer_text))
    return Decision(
        type=DecisionType.ANSWER,
        answer=answer_text,
        confidence=conf.score,
        threshold=decision_hint.threshold,
        citations=citations,
    )


def _handoff(
    trace: Trace,
    reason: str,
    confidence: float,
    threshold: float,
    customer_id: str | None,
) -> Decision:
    with tool_span("escalate_to_human", input={"reason": reason, "confidence": confidence}) as span:
        result = handoff_tool.escalate_to_human(
            reason=reason,
            transcript=trace.messages,
            confidence=confidence,
            customer_id=customer_id,
        )
        span.update(output={"ticket_id": result.ticket_id, "message": result.text})
    trace.messages.append(Message(role=Role.ASSISTANT, content=result.text))
    trace.spans.append(SpanRecord(name="handoff", kind="tool", attributes={"reason": reason}))
    return Decision(
        type=DecisionType.HANDOFF,
        answer=result.text,
        confidence=confidence,
        threshold=threshold,
        handoff_reason=reason,
        ticket_id=result.ticket_id,
    )


def _refusal_decision(message: str, threshold: float) -> Decision:
    return Decision(
        type=DecisionType.HANDOFF,
        answer=message,
        confidence=0.0,
        threshold=threshold,
        handoff_reason="refused at the input gate",
    )


def _anthropic_user(message: Message) -> dict:
    role = "user" if message.role in (Role.USER, Role.TOOL) else "assistant"
    return {"role": role, "content": message.content}


def _dedupe(citations: list[Citation]) -> list[Citation]:
    seen: set[tuple[str, str]] = set()
    unique: list[Citation] = []
    for c in citations:
        key = (c.source_id, c.chunk[:64])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique
