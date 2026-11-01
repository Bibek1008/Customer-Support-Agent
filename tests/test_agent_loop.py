"""End-to-end resolve path and end-to-end handoff path.

Both drive the real loop with a fake Anthropic client and a stubbed confidence
scorer, so the control flow (tool call, answer, confidence gate, handoff, cost
accounting) is exercised without a network call.
"""

from __future__ import annotations

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


def test_low_confidence_hands_off(make_client, monkeypatch):
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

    assert trace.decision.type == DecisionType.HANDOFF
    assert trace.decision.ticket_id is not None
    assert trace.decision.confidence == 0.15


def test_model_escalation_hands_off(make_client, monkeypatch):
    """If the model calls escalate_to_human, the loop opens a human ticket."""
    monkeypatch.setattr(
        loop_mod,
        "dispatch",
        lambda name, inp: ToolOutcome(text="", is_handoff=True, handoff_reason="needs a human"),
    )

    client = make_client(
        [
            FakeResponse(
                content=[
                    ToolUseBlock(id="t1", name="escalate_to_human", input={"reason": "needs a human"})
                ],
                stop_reason="tool_use",
            )
        ]
    )
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)

    trace = loop_mod.run_turn(conversation_id="c3", user_message="I need account recovery help")

    assert trace.decision.type == DecisionType.HANDOFF
    assert "needs a human" in (trace.decision.handoff_reason or "")
    assert trace.decision.ticket_id is not None
