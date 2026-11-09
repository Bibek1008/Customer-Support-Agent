"""End-to-end resolve path and end-to-end handoff path.

Both drive the real loop with a fake Anthropic client and a stubbed confidence
scorer, so the control flow (tool call, answer, confidence gate, handoff, cost
accounting) is exercised without a network call.
"""

from __future__ import annotations

from types import SimpleNamespace

import support_agent.agent.loop as loop_mod
from support_agent.schemas import Citation, DecisionType
from support_agent.tools.registry import ToolOutcome
from tests.conftest import FakeResponse, TextBlock, ToolUseBlock


class _Conf:
    def __init__(self, score: float):
        self.score = score
        self.reason = "test"
        self.cost_usd = 0.0


def test_resolve_path(make_client, monkeypatch):
    # KB tool returns a citation; the model then answers using it.
    citation = Citation(
        source_id="returns-policy",
        source_title="Returns and Refunds Policy",
        url=None,
        chunk="You can return most items within 30 days of delivery.",
        score=0.8,
    )
    monkeypatch.setattr(
        loop_mod,
        "dispatch",
        lambda name, inp: ToolOutcome(text=citation.chunk, citations=[citation]),
    )
    monkeypatch.setattr(loop_mod, "score_confidence", lambda **_: _Conf(0.9))

    client = make_client(
        [
            FakeResponse(
                content=[ToolUseBlock(id="t1", name="knowledge_base", input={"query": "returns"})],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[TextBlock("You can return items within 30 days of delivery.")],
                stop_reason="end_turn",
            ),
        ]
    )
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)

    trace = loop_mod.run_turn(conversation_id="c1", user_message="What is the return window?")

    assert trace.decision.type == DecisionType.ANSWER
    assert "30 days" in trace.decision.answer
    assert trace.decision.confidence == 0.9
    # The citation flowed through to the decision.
    assert any(c.source_id == "returns-policy" for c in trace.decision.citations)
    # Cost was accounted from the two model calls (arithmetic on usage fields).
    assert trace.total_usd() > 0


def test_model_that_skips_kb_gets_a_cited_synthetic_policy_fallback(make_client, monkeypatch):
    citation = Citation(
        source_id="returns-policy",
        source_title="Returns and Refunds Policy",
        url="https://help.example.com/returns",
        chunk="You can return most items within 30 days of delivery.",
        score=0.8,
    )
    calls = []

    def dispatch(name, inp):
        calls.append((name, inp))
        return ToolOutcome(text=citation.chunk, citations=[citation])

    monkeypatch.setattr(loop_mod, "dispatch", dispatch)
    monkeypatch.setattr(loop_mod, "score_confidence", lambda **_: _Conf(0.9))
    monkeypatch.setattr(
        loop_mod.refusal,
        "check_response",
        lambda _: SimpleNamespace(refuse=False),
    )
    client = make_client(
        [
            FakeResponse(
                content=[TextBlock("I don't know based on the available support information.")],
                stop_reason="end_turn",
            )
        ]
    )
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)

    trace = loop_mod.run_turn(
        conversation_id="c-fallback", user_message="What is your return policy?"
    )

    assert calls == [("knowledge_base", {"query": "What is your return policy?", "k": 4})]
    assert trace.decision.type == DecisionType.ANSWER
    assert "30 days" in trace.decision.answer
    assert trace.decision.citations[0].source_id == "returns-policy"
    assert any(span.name == "tool knowledge_base" for span in trace.spans)


def test_tool_output_pii_is_redacted_before_model_request(make_client, monkeypatch):
    sensitive_text = "Contact jane.doe@acme.com about SSN 123-45-6789."
    citation = Citation(
        source_id="case-123456789",
        source_title="Account record",
        url=None,
        chunk=sensitive_text,
        score=0.8,
    )
    monkeypatch.setattr(
        loop_mod,
        "dispatch",
        lambda name, inp: ToolOutcome(text=sensitive_text, citations=[citation]),
    )
    monkeypatch.setattr(loop_mod, "score_confidence", lambda **_: _Conf(0.9))
    client = make_client(
        [
            FakeResponse(
                content=[
                    ToolUseBlock(
                        id="sensitive-tool",
                        name="knowledge_base",
                        input={"query": "account"},
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[TextBlock("The account record is available.")], stop_reason="end_turn"
            ),
        ]
    )
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)

    trace = loop_mod.run_turn(conversation_id="pii-tool", user_message="Check my account")

    second_request = str(client.messages.calls[1]["messages"])
    assert "jane.doe@acme.com" not in second_request
    assert "123-45-6789" not in second_request
    assert "123456789" not in second_request
    assert "jane.doe@acme.com" not in str(trace.decision.citations)
    assert "123-45-6789" not in str(trace.decision.citations)


def test_missing_evidence_acknowledges_unknown_without_a_ticket(make_client, monkeypatch):
    monkeypatch.setattr(
        loop_mod, "dispatch", lambda name, inp: ToolOutcome(text="ambiguous", citations=[])
    )
    # Confidence below the default tau* (0.60) forces a handoff.
    monkeypatch.setattr(loop_mod, "score_confidence", lambda **_: _Conf(0.15))

    client = make_client(
        [
            FakeResponse(
                content=[ToolUseBlock(id="t1", name="knowledge_base", input={"query": "x"})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[TextBlock("I think maybe...")], stop_reason="end_turn"),
        ]
    )
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)

    trace = loop_mod.run_turn(conversation_id="c2", user_message="Something ambiguous")

    assert trace.decision.type == DecisionType.ANSWER
    assert trace.decision.ticket_id is None
    assert "I don't know" in trace.decision.answer
    assert not trace.decision.citations


def test_model_cannot_turn_missing_information_into_an_automatic_ticket(make_client, monkeypatch):
    """Explicit human requests route before the reasoning loop, via validated intent."""
    monkeypatch.setattr(
        loop_mod,
        "dispatch",
        lambda name, inp: ToolOutcome(text="", is_handoff=True, handoff_reason="needs a human"),
    )

    client = make_client(
        [
            FakeResponse(
                content=[
                    ToolUseBlock(
                        id="t1", name="escalate_to_human", input={"reason": "needs a human"}
                    )
                ],
                stop_reason="tool_use",
            )
        ]
    )
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)

    trace = loop_mod.run_turn(conversation_id="c3", user_message="I need account recovery help")

    assert trace.decision.type == DecisionType.ANSWER
    assert "I don't know" in trace.decision.answer
    assert trace.decision.ticket_id is None
