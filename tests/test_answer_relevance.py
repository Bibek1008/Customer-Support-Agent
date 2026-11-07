"""A verbatim but irrelevant source must not become a factual answer."""

import pytest

from support_agent.agent import loop
from support_agent.agent.confidence import ConfidenceResult
from support_agent.config import get_settings
from support_agent.schemas import Citation, Message, Trace


@pytest.mark.parametrize("mode", ["extractive", "generated"])
def test_irrelevant_source_is_rejected_without_creating_ticket(mode, monkeypatch):
    monkeypatch.setenv("ANSWER_MODE", mode)
    get_settings.cache_clear()
    source = Citation(
        source_id="returns",
        source_title="Returns",
        chunk="Return unused items within 30 days.",
        score=0.99,
    )
    calls = []

    def assess(**kwargs):
        calls.append(kwargs)
        return ConfidenceResult(
            score=0.0, reason="The source does not answer the product question."
        )

    monkeypatch.setattr(loop, "score_confidence", assess)
    monkeypatch.setattr(
        loop.handoff_tool,
        "escalate_to_human",
        lambda **_: pytest.fail("No automatic ticket for missing facts"),
    )
    trace = Trace(
        conversation_id="irrelevant",
        messages=[Message(role="user", content="What material is the Orion chair made of?")],
    )
    decision = loop._finalize(trace, source.chunk, [source], None, None)
    assert len(calls) == 1
    assert calls[0]["question"] == trace.messages[0].content
    assert "I don't know" in decision.answer
    assert source.chunk not in decision.answer
    assert not decision.citations and decision.ticket_id is None
    assert decision.confidence == 0.0


def test_relevant_extractive_source_requires_model_assessment(monkeypatch):
    monkeypatch.setenv("ANSWER_MODE", "extractive")
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    get_settings.cache_clear()
    source = Citation(
        source_id="returns",
        source_title="Returns",
        chunk="Return unused items within 30 days.",
        score=0.3,
    )
    monkeypatch.setattr(
        loop,
        "score_confidence",
        lambda **_: ConfidenceResult(score=0.9, reason="Answers the return-window question."),
    )
    trace = Trace(
        conversation_id="relevant",
        messages=[Message(role="user", content="How long do I have to return an item?")],
    )
    decision = loop._finalize(trace, "30 days", [source], None, None)
    assert source.chunk in decision.answer
    assert decision.confidence == 0.9
    assert decision.citations == [source]


def test_no_sources_means_unknown_not_a_ticket(monkeypatch):
    monkeypatch.setattr(
        loop, "score_confidence", lambda **_: pytest.fail("No need to score absent evidence")
    )
    monkeypatch.setattr(
        loop.handoff_tool, "escalate_to_human", lambda **_: pytest.fail("No ticket")
    )
    trace = Trace(
        conversation_id="no-evidence",
        messages=[Message(role="user", content="What is the desk's load capacity?")],
    )
    decision = loop._finalize(trace, "Possibly 100 kg", [], None, None)
    assert "I don't know" in decision.answer
    assert "100" not in decision.answer
    assert not decision.citations and decision.ticket_id is None
