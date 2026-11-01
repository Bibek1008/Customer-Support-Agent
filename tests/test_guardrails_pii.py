"""PII is redacted on input and never reaches logs or the model."""

from __future__ import annotations

from support_agent.guardrails.pii import get_redactor


def test_email_and_card_are_redacted():
    redactor = get_redactor()
    text = "My email is jane.doe@acme.com and my card is 4111 1111 1111 1111."
    result = redactor.redact(text)

    assert "jane.doe@acme.com" not in result.text
    assert "4111 1111 1111 1111" not in result.text
    assert result.had_pii
    # The placeholder keeps the sentence readable.
    assert "<EMAIL_ADDRESS>" in result.text or "<CREDIT_CARD>" in result.text


def test_ssn_is_redacted():
    result = get_redactor().redact("My SSN is 123-45-6789, please help.")
    assert "123-45-6789" not in result.text
    assert result.had_pii


def test_clean_text_is_left_alone():
    result = get_redactor().redact("How long is the return window?")
    assert not result.had_pii
    assert result.text == "How long is the return window?"


def test_redacted_text_is_what_gets_stored(make_client, monkeypatch):
    """The message the loop stores must already be redacted, so raw PII never
    lands in a trace or a log."""
    from tests.conftest import FakeResponse, TextBlock

    import support_agent.agent.loop as loop_mod

    # Model answers immediately with no tool calls.
    client = make_client([FakeResponse(content=[TextBlock("Sure, here is help.")], stop_reason="end_turn")])
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)
    monkeypatch.setattr(loop_mod, "score_confidence", lambda **_: _Conf(0.9))

    trace = loop_mod.run_turn(
        conversation_id="c1",
        user_message="My email is bob@acme.com, what is your return window?",
    )

    stored_user = trace.messages[0].content
    assert "bob@acme.com" not in stored_user
    assert "<EMAIL_ADDRESS>" in stored_user


class _Conf:
    def __init__(self, score: float):
        self.score = score
        self.reason = "test"
        self.cost_usd = 0.0
