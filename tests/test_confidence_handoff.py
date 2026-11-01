"""Below tau*, the agent escalates instead of answering."""

from __future__ import annotations

from support_agent.agent.confidence import decide_handoff


def test_below_threshold_hands_off():
    decision = decide_handoff(confidence=0.20, threshold=0.60)
    assert decision.handoff
    assert decision.threshold == 0.60


def test_at_threshold_answers():
    # handoff = confidence < tau, so equality answers.
    decision = decide_handoff(confidence=0.60, threshold=0.60)
    assert not decision.handoff


def test_above_threshold_answers():
    decision = decide_handoff(confidence=0.95, threshold=0.60)
    assert not decision.handoff


def test_default_threshold_from_settings(monkeypatch):
    monkeypatch.setenv("HANDOFF_THRESHOLD", "0.75")
    from support_agent.config import get_settings

    get_settings.cache_clear()
    decision = decide_handoff(confidence=0.70)  # no explicit threshold
    assert decision.threshold == 0.75
    assert decision.handoff  # 0.70 < 0.75
