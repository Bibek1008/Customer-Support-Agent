"""PII is redacted on input and never reaches logs or the model."""

from __future__ import annotations

import logging
import sys
from types import ModuleType

import pytest

from support_agent.guardrails.pii import get_redactor


def test_presidio_uses_the_small_installed_spacy_model(monkeypatch):
    from support_agent.guardrails import pii
    from support_agent.guardrails.pii import PIIRedactor

    observed = {}
    engine = object()

    class Provider:
        def __init__(self, *, nlp_configuration):
            observed["configuration"] = nlp_configuration

        def create_engine(self):
            return engine

    class Analyzer:
        def __init__(self, *, nlp_engine, supported_languages):
            observed["engine"] = nlp_engine
            observed["languages"] = supported_languages

    presidio = ModuleType("presidio_analyzer")
    presidio.AnalyzerEngine = Analyzer
    nlp_engine = ModuleType("presidio_analyzer.nlp_engine")
    nlp_engine.NlpEngineProvider = Provider
    anonymizer = ModuleType("presidio_anonymizer")
    anonymizer.AnonymizerEngine = object
    monkeypatch.setitem(sys.modules, "presidio_analyzer", presidio)
    monkeypatch.setitem(sys.modules, "presidio_analyzer.nlp_engine", nlp_engine)
    monkeypatch.setitem(sys.modules, "presidio_anonymizer", anonymizer)
    requested_models = []
    monkeypatch.setattr(
        pii, "find_spec", lambda model_name: requested_models.append(model_name) or object()
    )

    redactor = PIIRedactor.__new__(PIIRedactor)
    assert redactor._try_load_presidio()

    assert observed["configuration"]["models"] == [
        {"lang_code": "en", "model_name": "en_core_web_sm"}
    ]
    assert requested_models == ["en_core_web_sm"]
    assert observed["engine"] is engine
    assert observed["languages"] == ["en"]


def test_missing_spacy_model_fails_without_attempting_model_download(monkeypatch):
    from support_agent.guardrails import pii
    from support_agent.guardrails.pii import PIIRedactor

    class UnexpectedProvider:
        def __init__(self, **kwargs):
            pytest.fail("Presidio provider must not load or download a missing model")

    presidio = ModuleType("presidio_analyzer")
    presidio.AnalyzerEngine = object
    nlp_engine = ModuleType("presidio_analyzer.nlp_engine")
    nlp_engine.NlpEngineProvider = UnexpectedProvider
    anonymizer = ModuleType("presidio_anonymizer")
    anonymizer.AnonymizerEngine = object
    monkeypatch.setitem(sys.modules, "presidio_analyzer", presidio)
    monkeypatch.setitem(sys.modules, "presidio_analyzer.nlp_engine", nlp_engine)
    monkeypatch.setitem(sys.modules, "presidio_anonymizer", anonymizer)
    requested_models = []
    monkeypatch.setattr(
        pii, "find_spec", lambda model_name: requested_models.append(model_name) or None
    )

    redactor = PIIRedactor.__new__(PIIRedactor)
    assert redactor._try_load_presidio() is False
    assert requested_models == ["en_core_web_sm"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Email jane.doe@example.com", "<EMAIL_ADDRESS>"),
        ("Call +1 212-555-0100", "<PHONE_NUMBER>"),
        ("Card 4111 1111 1111 1111", "<CREDIT_CARD>"),
        ("IP 192.0.2.44", "<IP_ADDRESS>"),
        ("SSN 123-45-6789", "<US_SSN>"),
    ],
)
def test_presidio_redacts_common_pii_types(text, expected):
    result = get_redactor().redact(text)
    assert expected in result.text
    assert result.had_pii


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
    assert result.text == "My SSN is <US_SSN>, please help."
    assert result.entities == ["US_SSN"]
    assert result.had_pii


@pytest.mark.parametrize(
    ("text", "raw_ssn"),
    [
        ("My SSN is 123-45-6789, thanks.", "123-45-6789"),
        ("My SSN is 123 45 6789, thanks.", "123 45 6789"),
        ("My SSN is 123456789, thanks.", "123456789"),
    ],
)
def test_ssn_formats_are_redacted_without_losing_surrounding_text(text, raw_ssn):
    result = get_redactor().redact(text)

    assert raw_ssn not in result.text
    assert result.text == text.replace(raw_ssn, "<US_SSN>")
    assert result.entities.count("US_SSN") == 1


@pytest.mark.parametrize(
    "text",
    [
        "The return window is 30 days.",
        "Order reference 123456789 is still processing.",
        "This date is 2026-11-01.",
        "Invalid SSN 000-12-1234 should not match the SSN rule.",
        "Invalid SSN 666-12-1234 should not match the SSN rule.",
        "Invalid SSN 123-00-1234 should not match the SSN rule.",
    ],
)
def test_non_ssn_text_is_not_matched_by_deterministic_ssn_rule(text):
    from support_agent.guardrails.pii import PIIRedactor

    result = PIIRedactor.__new__(PIIRedactor)._redact_ssn(text)

    assert result.text == text
    assert result.entities == []


@pytest.mark.parametrize(
    "text",
    [
        "Your return window is 30 days.",
        "Your order reference 123456789 is still processing.",
        "The shipping update is due in 5 business days.",
        "Hardware has a one-year limited warranty.",
    ],
)
def test_common_numbers_are_preserved_by_the_full_redactor(text):
    result = get_redactor().redact(text)

    assert result.text == text
    assert not result.had_pii


def test_presidio_error_uses_fallback_without_logging_input(caplog, monkeypatch):
    redactor = get_redactor()

    class BrokenAnalyzer:
        def analyze(self, **kwargs):
            raise RuntimeError(f"detector failed on {kwargs['text']}")

    monkeypatch.setattr(redactor, "_presidio", True)
    monkeypatch.setattr(redactor, "_analyzer", BrokenAnalyzer())
    text = "My SSN is 123-45-6789 and email is jane.doe@acme.com."

    with caplog.at_level(logging.WARNING):
        result = redactor.redact(text)

    assert "123-45-6789" not in result.text
    assert "jane.doe@acme.com" not in result.text
    assert result.text == "My SSN is <US_SSN> and email is <EMAIL_ADDRESS>."
    assert "123-45-6789" not in caplog.text
    assert "jane.doe@acme.com" not in caplog.text


def test_clean_text_is_left_alone():
    result = get_redactor().redact("How long is the return window?")
    assert not result.had_pii
    assert result.text == "How long is the return window?"


def test_redacted_text_is_stored_and_sent_to_model(make_client, monkeypatch, caplog):
    """Raw PII is removed from traces, history, and model requests."""
    import support_agent.agent.loop as loop_mod
    from support_agent.schemas import Message, Role
    from tests.conftest import FakeResponse, TextBlock

    # Model answers immediately with no tool calls.
    client = make_client(
        [FakeResponse(content=[TextBlock("Sure, here is help.")], stop_reason="end_turn")]
    )
    monkeypatch.setattr(loop_mod, "get_client", lambda: client)
    monkeypatch.setattr(loop_mod, "score_confidence", lambda **_: _Conf(0.9))

    with caplog.at_level(logging.DEBUG):
        trace = loop_mod.run_turn(
            conversation_id="c1",
            user_message="My email is bob@acme.com, what is your return window?",
            history=[
                Message(
                    role=Role.USER,
                    content="My old SSN is 123-45-6789.",
                )
            ],
        )

    stored_user = next(
        message.content
        for message in trace.messages
        if message.role is Role.USER and "return window" in message.content
    )
    assert "bob@acme.com" not in stored_user
    assert "<EMAIL_ADDRESS>" in stored_user
    assert "123-45-6789" not in trace.messages[0].content
    serialized_request = str(client.messages.calls[0]["messages"])
    assert "bob@acme.com" not in serialized_request
    assert "123-45-6789" not in serialized_request
    assert "bob@acme.com" not in caplog.text
    assert "123-45-6789" not in caplog.text


class _Conf:
    def __init__(self, score: float):
        self.score = score
        self.reason = "test"
        self.cost_usd = 0.0
