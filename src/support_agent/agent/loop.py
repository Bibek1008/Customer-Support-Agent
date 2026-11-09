"""The agent loop over the Claude tool runner.

One run handles one customer turn end to end:

1. Redact PII from the input, then gate it (disallowed / out of scope).
2. Run the manual tool-use loop on Claude Opus 4.8. Every tool result is passed
   through the injection quarantine before the model reads it, and the cost of
   every model call is recorded on a span.
3. When the model produces an answer, score its confidence against the sources
   it retrieved and check that the evidence answers the question. Missing or
   irrelevant evidence produces an honest unknown answer, without a ticket.
4. Gate the final answer with the safety classifier before returning it.

We use a manual loop rather than the SDK tool runner because two things have to
happen on every tool result (injection quarantine and per-step cost/tracing), and
the answer has to be graded for confidence before it is allowed out. Those are
cross-cutting steps the manual loop makes explicit.
"""

from __future__ import annotations

import json
import re

from support_agent.agent.confidence import decide_handoff, score_confidence
from support_agent.agent.models import get_client, reasoner_kwargs
from support_agent.agent.prompts import OLIST_SYSTEM_PROMPT, SYSTEM_PROMPT
from support_agent.config import get_settings
from support_agent.guardrails import refusal
from support_agent.guardrails.conversation import (
    Intent,
    classify_intent,
    conversational_reply,
    existing_handoff,
)
from support_agent.guardrails.injection import quarantine_tool_output
from support_agent.guardrails.pii import get_redactor
from support_agent.observability.cost import cost_from_usage
from support_agent.observability.tracing import (
    guardrail_span,
    model_span,
    record_request_input,
    sanitize,
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
from support_agent.tools.registry import dispatch, tool_schemas


@trace_turn
def run_turn(
    conversation_id: str,
    user_message: str,
    customer_id: str | None = None,
    history: list[Message] | None = None,
) -> Trace:
    """Run one customer turn through the agent and return the full trace."""
    settings = get_settings()
    from support_agent.request_context import current_request

    request_context = current_request.get()
    olist_mode = bool(request_context and request_context.kb_profile == "olist_demo")
    system_prompt = OLIST_SYSTEM_PROMPT if olist_mode else SYSTEM_PROMPT
    available_tools = tool_schemas()
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

    intent = classify_intent(redacted.text, prior)
    if intent._cost_record is not None:
        trace.spans.append(
            SpanRecord(
                name="classify-intent",
                kind="model",
                cost=intent._cost_record,
                attributes={"intent": intent.intent.value},
            )
        )
    with guardrail_span("conversation_scope") as span:
        span.set("guardrail.conversation_category", intent.intent.value)
    trace.spans.append(
        SpanRecord(
            name="conversation_scope",
            kind="guardrail",
            attributes={"category": intent.intent.value},
        )
    )
    conversation_reply = conversational_reply(intent, prior, redacted.text)
    if conversation_reply is not None:
        trace.decision = Decision(
            type=DecisionType.ANSWER,
            answer=conversation_reply,
            confidence=1.0,
            threshold=settings.handoff_threshold,
        )
        trace.messages.append(Message(role=Role.ASSISTANT, content=conversation_reply))
        return trace

    # 2. Input guardrail: disallowed or out of scope -> refuse without a loop.
    gate = refusal.check_input(redacted.text)
    if gate.refuse:
        trace.decision = _refusal_decision(gate.message, settings.handoff_threshold)
        trace.messages.append(Message(role=Role.ASSISTANT, content=gate.message))
        return trace

    if intent.intent == Intent.HUMAN:
        reference = existing_handoff(prior)
        prefix = (
            "I don't have a verified support phone number to share. "
            if intent.phone_requested
            else ""
        )
        if reference:
            text = (
                prefix
                + f"Your existing request is saved for staff review. Your reference is {reference}. You can check this chat for a reply; a response time isn't guaranteed."
            )
            trace.decision = Decision(
                type=DecisionType.ANSWER,
                answer=text,
                confidence=1.0,
                threshold=settings.handoff_threshold,
            )
            trace.messages.append(Message(role=Role.ASSISTANT, content=text))
        else:
            trace.decision = _handoff(
                trace,
                "Customer requested a human agent.",
                0.0,
                settings.handoff_threshold,
                customer_id,
            )
            text = (
                prefix
                + f"I've saved your request to speak with staff. Your reference is {trace.decision.ticket_id}. You can check this chat for a staff reply; a response time isn't guaranteed."
            )
            trace.decision.answer = text
            trace.messages[-1].content = text
        return trace

    if settings.pricing_requires_review and intent.intent == Intent.PRICING:
        trace.decision = _handoff(
            trace,
            "Pricing and promotions require staff review; no approved pricing policy is connected.",
            0.0,
            settings.handoff_threshold,
            customer_id,
        )
        return trace

    if intent.intent == Intent.ACCOUNT_RECOVERY:
        trace.decision = _handoff(
            trace,
            "Account recovery requires staff identity verification.",
            0.0,
            settings.handoff_threshold,
            customer_id,
        )
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
            input=[{"role": "system", "content": system_prompt}, *messages],
        ) as span:
            span.update(
                metadata={"tools": available_tools},
                model_parameters={
                    "max_tokens": kwargs["max_tokens"],
                    "reasoning_effort": kwargs.get("output_config", {}).get("effort", "low"),
                },
            )
            resp = get_client().messages.create(
                **kwargs,
                system=system_prompt,
                tools=available_tools,
                messages=messages,
            )
            cost = cost_from_usage(kwargs["model"], resp.usage)
            span.record_cost(cost)
            span.record_response(resp)
        trace.spans.append(
            SpanRecord(
                name="generate-response",
                kind="model",
                cost=cost,
                attributes={
                    "model": kwargs["model"],
                    "input": sanitize(messages),
                    "output": sanitize(resp.content),
                },
            )
        )

        if resp.stop_reason == "refusal":
            # Do not retry or fabricate an answer after a model refusal.
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

    # 4. Release a relevant supported answer, or acknowledge missing knowledge.
    trace.decision = _finalize(
        trace=trace,
        answer_text=answer_text,
        citations=_dedupe(citations),
        handoff_reason=handoff_reason,
        customer_id=customer_id,
        extractive=not olist_mode,
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
    trace.spans.append(
        SpanRecord(
            name=f"tool {block.name}",
            kind="tool",
            attributes={
                "input": sanitize(tool_input),
                "output": sanitize(outcome),
                "unavailable_reason": outcome.unavailable_reason,
            },
        )
    )
    return outcome


def _finalize(
    trace: Trace,
    answer_text: str,
    citations: list[Citation],
    handoff_reason: str | None,
    customer_id: str | None,
    extractive: bool = True,
) -> Decision:
    settings = get_settings()
    question = next((m.content for m in reversed(trace.messages) if m.role == Role.USER), "")
    from support_agent.request_context import current_request

    context = current_request.get()
    if not citations and any(
        span.attributes.get("unavailable_reason") == "knowledge_profile_not_initialized"
        for span in trace.spans
    ):
        text = (
            "The Brazilian consumer-rights knowledge base has not been initialized for this app yet. "
            "Its legal documents still need to be indexed before I can provide a sourced answer. "
            "This is a setup issue, rather than missing details about your question."
            if context and context.kb_profile == "olist_demo"
            else "The support knowledge base has not been initialized for this app yet. Its documents need to be indexed before I can provide a sourced answer."
        )
        return _unknown(trace, "knowledge_profile_not_initialized", message=text)
    if context and context.kb_profile == "olist_demo" and handoff_reason:
        return _handoff(trace, handoff_reason, 0.0, settings.handoff_threshold, customer_id)

    # A missing answer or evidence is not permission to open a staff ticket.
    # Explicit human requests and verification-required actions route earlier.
    if handoff_reason is not None or not answer_text:
        return _unknown(trace, handoff_reason or "No grounded answer was produced.")
    if not citations:
        return _unknown(trace, "No supporting sources were retrieved.")
    if (
        context
        and context.kb_profile == "olist_demo"
        and re.search(r"\b[0-9a-fA-F]{32}\b", answer_text)
    ):
        return _unknown(
            trace, "Internal dataset identifiers cannot appear in customer-facing answers."
        )
    if (
        context
        and context.kb_profile == "olist_demo"
        and re.search(
            r"\b(?:Olist(?:'s|’s)?|our|the merchant(?:'s|’s)?) (?:official |company )?(?:return|refund|warranty|cancellation|shipping) polic(?:y|ies) (?:is|are|allows?|requires?|provides?|offers?)\b",
            answer_text,
            re.IGNORECASE,
        )
    ):
        return _unknown(
            trace,
            "No verified Olist merchant policy is available; general law is not merchant terms.",
        )

    # Score confidence against the sources actually retrieved, then apply tau*.
    if settings.answer_mode == "extractive" and extractive:
        safe_sources = [
            source
            for source in citations
            if not quarantine_tool_output("source", source.chunk).triggered
        ]
        if not safe_sources:
            return _unknown(trace, "No safe source excerpt was available.")
        source = max(safe_sources, key=lambda item: item.score)
        answer_text = f"{source.source_title}:\n\n{source.chunk}\n\nSource: {source.source_id}."
        citations = [source]
        # A matching quotation can still be irrelevant. Judge it against the
        # customer's actual question before releasing the excerpt.
        conf = score_confidence(question=question, answer=answer_text, citations=citations)
    else:
        # Writing tools can only create/update tickets. A model must not claim
        # refunds, password changes, or invented ticket IDs as completed actions.
        unsupported_action = re.search(
            r"\b(?:i|we)(?: have|ve|’ve|'ve)? (?:created|issued|processed|cancelled|canceled|reset|sent|opened)\b|will follow up|will reach out",
            answer_text,
            re.IGNORECASE,
        )
        if unsupported_action:
            return _handoff(
                trace,
                "The draft claimed an action that requires staff verification.",
                0.0,
                settings.handoff_threshold,
                customer_id,
            )
        conf = score_confidence(question=question, answer=answer_text, citations=citations)
    trace.spans.append(
        SpanRecord(
            name="confidence",
            kind="model",
            cost=getattr(conf, "cost_record", None),
            attributes={"score": conf.score, "reason": conf.reason},
        )
    )
    decision_hint = decide_handoff(conf.score, settings.handoff_threshold)
    if decision_hint.handoff:
        return _unknown(trace, "The sources did not establish a relevant, supported answer.")

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

    answer_text = get_redactor().redact(answer_text).text
    trace.messages.append(Message(role=Role.ASSISTANT, content=answer_text))
    return Decision(
        type=DecisionType.ANSWER,
        answer=answer_text,
        confidence=conf.score,
        threshold=decision_hint.threshold,
        citations=citations,
    )


def _unknown(trace: Trace, reason: str, message: str | None = None) -> Decision:
    text = message or (
        "I don't know based on the approved support information available. "
        "Please share more details, or ask for staff review if you'd like help from a person."
    )
    with guardrail_span("knowledge_abstention") as span:
        span.set("guardrail.abstention.reason", reason)
    trace.spans.append(
        SpanRecord(name="knowledge_abstention", kind="guardrail", attributes={"reason": reason})
    )
    trace.messages.append(Message(role=Role.ASSISTANT, content=text))
    return Decision(
        type=DecisionType.ANSWER,
        answer=text,
        confidence=0.0,
        threshold=get_settings().handoff_threshold,
        citations=[],
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
