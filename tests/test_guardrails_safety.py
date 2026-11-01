"""Unsafe input and unsafe response are both caught by the Llama Guard 4 client."""

from __future__ import annotations

from support_agent.guardrails.safety import SafetyClassifier, SafetyRole, get_classifier


def test_parse_safe():
    verdict = SafetyClassifier._parse("safe")
    assert verdict.safe
    assert verdict.categories == []
    assert not verdict.blocked


def test_parse_unsafe_with_categories():
    verdict = SafetyClassifier._parse("unsafe\nS1,S3")
    assert not verdict.safe
    assert verdict.categories == ["S1", "S3"]
    assert verdict.blocked


def test_no_server_is_unchecked_not_blocked(monkeypatch):
    """With no safety server configured, the classifier reports unchecked rather
    than silently blocking, so local development is not stuck — but a deployment
    must set SAFETY_MODEL_URL."""
    monkeypatch.delenv("SAFETY_MODEL_URL", raising=False)
    from support_agent.config import get_settings

    get_settings.cache_clear()
    # Fresh classifier so it re-reads settings.
    import support_agent.guardrails.safety as safety_mod

    safety_mod._CLASSIFIER = None
    verdict = get_classifier().classify("hello", role=SafetyRole.USER)
    assert not verdict.checked
    assert not verdict.blocked


def test_server_outage_blocks(monkeypatch):
    """If the safety server is configured but unreachable, unsafe content must
    not pass — the classifier blocks."""
    monkeypatch.setenv("SAFETY_MODEL_URL", "http://127.0.0.1:9/v1")  # unreachable
    from support_agent.config import get_settings

    get_settings.cache_clear()
    import support_agent.guardrails.safety as safety_mod

    safety_mod._CLASSIFIER = None
    verdict = get_classifier().classify("some text", role=SafetyRole.ASSISTANT)
    assert verdict.checked
    assert verdict.blocked
    assert "UNAVAILABLE" in verdict.categories
