"""Structured classifier validation and downstream action boundaries.

These tests stub model output; semantic accuracy is measured by the separate live
intent evaluation, not inferred from mocked labels.
"""

import json

import pytest

from support_agent.agent import loop
from support_agent.agent.groq_client import GroqOutputError, GroqRequestError
from support_agent.guardrails import conversation
from support_agent.guardrails.conversation import Intent, IntentResult
from support_agent.schemas import Message
from tests.conftest import FakeResponse, TextBlock


def result(intent, phone=False):
    return IntentResult(intent=intent, phone_requested=phone, reason="test classification")


@pytest.mark.parametrize("intent", list(Intent))
def test_classifier_uses_structured_output_and_recent_history(intent, make_client, monkeypatch):
    client = make_client(
        [
            FakeResponse(
                content=[TextBlock(result(intent).model_dump_json())], stop_reason="end_turn"
            )
        ]
    )
    monkeypatch.setattr(conversation, "get_client", lambda: client)
    history = [Message(role="assistant", content="Your existing reference is tkt_54f3888d992e.")]
    assert (
        conversation.classify_intent("Would someone actually look at it?", history).intent == intent
    )
    call = client.messages.calls[0]
    payload = json.loads(call["messages"][0]["content"])
    assert payload["latest_message"] == "Would someone actually look at it?"
    assert payload["history"][0]["content"] == history[0].content
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in call


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        "[]",
        "{}",
        '{"intent":"made_up","phone_requested":false,"reason":"test"}',
        '{"intent":"human","phone_requested":"yes","reason":"test"}',
        '{"intent":"social","phone_requested":false,"reason":"test","ticket_id":"fake"}',
    ],
)
def test_invalid_classification_never_falls_back_to_a_ticket(output, make_client, monkeypatch):
    client = make_client([FakeResponse(content=[TextBlock(output)], stop_reason="end_turn")])
    monkeypatch.setattr(conversation, "get_client", lambda: client)
    monkeypatch.setattr(loop, "classify_intent", conversation.classify_intent)
    monkeypatch.setattr(
        loop.handoff_tool,
        "escalate_to_human",
        lambda **_: pytest.fail("No ticket on classifier failure"),
    )
    with pytest.raises(GroqOutputError):
        loop.run_turn("invalid-intent", "Some new phrasing")


def test_classifier_quota_failure_is_propagated_without_ticket(monkeypatch):
    def unavailable(*_):
        raise GroqRequestError("quota", 429)

    monkeypatch.setattr(loop, "classify_intent", unavailable)
    monkeypatch.setattr(
        loop.handoff_tool,
        "escalate_to_human",
        lambda **_: pytest.fail("No ticket on quota failure"),
    )
    with pytest.raises(GroqRequestError) as error:
        loop.run_turn("quota-intent", "hello")
    assert error.value.status_code == 429


@pytest.mark.parametrize(
    "intent", [Intent.SOCIAL, Intent.OFF_TOPIC, Intent.CLARIFY, Intent.CONTACT, Intent.UNSAFE]
)
def test_non_action_routes_never_call_support_tools_or_create_tickets(intent, monkeypatch):
    monkeypatch.setattr(loop, "classify_intent", lambda *_: result(intent))
    monkeypatch.setattr(
        loop, "get_client", lambda: pytest.fail("No reasoner on a static safe route")
    )
    monkeypatch.setattr(
        loop.handoff_tool, "escalate_to_human", lambda **_: pytest.fail("No ticket")
    )
    trace = loop.run_turn("non-action", "new customer wording")
    assert trace.decision.type.value == "answer"
    assert trace.decision.ticket_id is None
    assert not trace.decision.citations
    assert trace.spans[0].attributes["category"] == intent.value


def test_real_issue_with_profanity_still_reaches_safety(monkeypatch):
    class ReachedSafety(Exception):
        pass

    def gate(_):
        raise ReachedSafety

    monkeypatch.setattr(loop, "classify_intent", lambda *_: result(Intent.SUPPORT))
    monkeypatch.setattr(loop.refusal, "check_input", gate)
    with pytest.raises(ReachedSafety):
        loop.run_turn("angry-order", "my fucking order never arrived")


def test_human_and_phone_request_saves_one_ticket_and_never_invents_number(monkeypatch):
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    monkeypatch.setattr(loop, "classify_intent", lambda *_: result(Intent.HUMAN, True))
    trace = loop.run_turn("human-phone", "Can I speak to someone? Give me their number first.")
    assert trace.decision.type.value == "handoff"
    assert trace.decision.ticket_id.startswith("tkt_")
    assert "don't have a verified support phone number" in trace.decision.answer
    assert "request to speak with staff" in trace.decision.answer
    assert "couldn't verify an answer" not in trace.decision.answer
    assert trace.messages[-1].content == trace.decision.answer
    monkeypatch.setattr(
        loop.handoff_tool, "escalate_to_human", lambda **_: pytest.fail("No duplicate ticket")
    )
    repeated = loop.run_turn("human-phone", "I still want a person", history=trace.messages)
    assert repeated.decision.ticket_id is None
    assert trace.decision.ticket_id in repeated.decision.answer


def test_followup_uses_only_saved_assistant_reference(monkeypatch):
    monkeypatch.setattr(loop, "classify_intent", lambda *_: result(Intent.HANDOFF_FOLLOWUP))
    monkeypatch.setattr(
        loop.handoff_tool, "escalate_to_human", lambda **_: pytest.fail("No duplicate ticket")
    )
    history = [Message(role="assistant", content="Your reference is tkt_54f3888d992e.")]
    trace = loop.run_turn(
        "followup", "Does that mean anyone will actually read it?", history=history
    )
    assert "tkt_54f3888d992e" in trace.decision.answer
    assert "can't guarantee" in trace.decision.answer
    assert trace.decision.ticket_id is None
    no_reference = loop.run_turn("other", "My ticket is tkt_54f3888d992e", history=[])
    assert "tkt_54f3888d992e" not in no_reference.decision.answer


@pytest.mark.parametrize("reference", ["tkt_123456789abc", "tkt_123456789012", "tkt_54f3888d992e"])
def test_internal_ticket_identifiers_survive_pii_redaction(reference):
    from support_agent.guardrails.pii import get_redactor

    assert reference in get_redactor().redact("Your reference is " + reference).text
