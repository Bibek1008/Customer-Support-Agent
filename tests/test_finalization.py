"""Production cancellation regression, with isolated providers and persistence."""

import json
import re
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from support_agent import http_api, repository, server
from support_agent.agent import confidence, finalization, loop
from support_agent.agent.confidence import ConfidenceResult
from support_agent.config import get_settings
from support_agent.guardrails import pii
from support_agent.guardrails.redaction import URL_PATTERN, public_document_url
from support_agent.observability.tracing import sanitize
from support_agent.schemas import Citation, Decision, Message, Trace
from tests.conftest import FakeResponse, TextBlock, ToolUseBlock

PUBLIC_URL = "https://help.example.com/billing"
POLICY = (
    "Subscriptions renew automatically on the same day each month. "
    "To cancel, go to Billing and choose Cancel. Cancellation takes effect at the "
    "end of the current billing period; you keep access until then and are not charged again. "
    "Verified duplicate or post-cancellation charges are refunded to the original payment "
    "method within 5 to 7 business days."
)


def approved_source(**updates):
    source = Citation(
        source_id="billing",
        source_title="Billing and Subscriptions",
        chunk=POLICY,
        url=PUBLIC_URL,
        score=0.71,
    ).model_copy(update=updates)
    source._approved_kb = True
    return source


@pytest.fixture
def detector(monkeypatch):
    """Simulate Presidio's observed false positive, independently of local spaCy."""

    def analyze(*, text, language):
        entities = []
        for kind, pattern in [
            ("DATE_TIME", re.compile("the same day each month|November 1, 2026")),
            ("URL", URL_PATTERN),
            ("EMAIL_ADDRESS", re.compile(r"\b[\w.+-]+@[\w.-]+\b")),
        ]:
            entities.extend(
                SimpleNamespace(entity_type=kind, start=m.start(), end=m.end())
                for m in pattern.finditer(text)
            )
        return entities

    def anonymize(*, text, analyzer_results, operators):
        for result in sorted(analyzer_results, key=lambda r: r.start, reverse=True):
            text = text[: result.start] + f"<{result.entity_type}>" + text[result.end :]
        return SimpleNamespace(text=text)

    redactor = object.__new__(pii.PIIRedactor)
    redactor._presidio = True
    redactor._analyzer = SimpleNamespace(analyze=analyze)
    redactor._anonymizer = SimpleNamespace(anonymize=anonymize)
    for module in (pii, finalization, loop, http_api):
        monkeypatch.setattr(module, "get_redactor", lambda: redactor)
    return redactor


def test_provenance_preserves_only_safe_policy_content(detector):
    source = approved_source(
        chunk=POLICY + " Contact jane@example.com. Effective November 1, 2026."
    )
    result = finalization.sanitize_citations([source])[0]
    assert result.url == PUBLIC_URL
    assert result.source_id == "billing"
    assert result.source_title == "Billing and Subscriptions"
    assert "the same day each month" in result.chunk
    assert "jane@example.com" not in result.chunk
    assert "<EMAIL_ADDRESS>" in result.chunk
    assert "November 1, 2026" not in result.chunk  # No blanket date exemption.
    assert "<DATE_TIME>" in result.chunk
    assert "<DATE_TIME>" in detector.redact("the same day each month").text
    assert detector.redact(PUBLIC_URL).text == "<URL>"


def test_json_cannot_grant_kb_provenance(detector):
    payload = approved_source().model_dump()
    payload["_approved_kb"] = True
    source = Citation.model_validate(payload)
    sanitized = finalization.sanitize_citations([source])[0]
    assert not source._approved_kb
    assert sanitized.url is None
    assert "<DATE_TIME>" in sanitized.chunk


def test_real_retrieval_attaches_server_provenance(kb):
    from support_agent.tools.knowledge_base import search_knowledge_base

    result = search_knowledge_base(
        "Subscriptions renew automatically Billing page cancel subscription current billing period"
    )
    assert result.citations
    assert all(c._approved_kb for c in result.citations)
    assert any(c.url == PUBLIC_URL for c in finalization.sanitize_citations(result.citations))


@pytest.mark.parametrize(
    "url",
    [
        "https://help.example.com/billing?token=secret",
        "https://help.example.com/billing#secret",
        "https://user:password@help.example.com/billing",
        "http://127.0.0.1/billing",
        "http://[::1]/billing",
        "http://localhost/billing",
        "https://help.internal/billing",
        "https://private.example.com/billing",
        "https://help.example.com:8443/billing",
        "javascript:alert(1)",
        "https://help.example.com/%74oken/secret",
        "https://help.example.com/reset/secret",
        "https://help.example.com/" + "a" * 32,
        "https://help.example.com\\@127.0.0.1/billing",
        "https://help.example.com/../billing",
    ],
)
def test_private_or_ambiguous_citation_urls_are_omitted(url, detector):
    assert not public_document_url(url)
    assert finalization.sanitize_citations([approved_source(url=url)])[0].url is None


@pytest.mark.parametrize("presidio", [True, False])
def test_secrets_are_removed_from_customer_content_and_observability(
    detector, monkeypatch, presidio
):
    monkeypatch.setenv("GROQ_API_KEY", "configured-secret-example")
    get_settings.cache_clear()
    detector._presidio = presidio
    text = (
        "jane@example.com https://help.example.com/billing?token=private-query "
        "Authorization: Bearer abcdefghijklmnop api_key=credential123 "
        "password=password123 sk-proj-abcdefghijklmnop configured-secret-example "
        "postgresql://user:db-password@private.example.com/db"
    )
    for result in (detector.redact(text).text, sanitize(text)):
        for secret in (
            "jane@example.com",
            "private-query",
            "abcdefghijklmnop",
            "credential123",
            "password123",
            "configured-secret-example",
            "db-password",
        ):
            assert secret not in result


@pytest.mark.parametrize(
    "text,secret",
    [
        ('{"password": "sensitive-value"}', "sensitive-value"),
        ("My password is sensitive-value", "sensitive-value"),
        ('{"access_token":"sensitive-value"}', "sensitive-value"),
        ("https://help.example.com/billing?token=first)second", "second"),
        ("ftp://user:sensitive-value@files.example.com/private", "sensitive-value"),
    ],
)
def test_credentials_in_structured_text_and_private_uris_are_protected(text, secret, detector):
    assert secret not in detector.redact(text).text
    assert secret not in sanitize(text)


def test_structured_observability_credentials_are_masked_by_field_name():
    data = {
        "password": "an-unknown-value",
        "access_token": "another-unknown-value",
        "metadata": {"Authorization": "opaque-value", "custom_api_key": "unknown-key"},
    }
    masked = sanitize(data)
    assert masked == {
        "password": "<SECRET>",
        "access_token": "<SECRET>",
        "metadata": {"Authorization": "<SECRET>", "custom_api_key": "<SECRET>"},
    }


class IsolatedRepository:
    def __init__(self):
        self.canonical = None
        self.persisted = None
        self.sql = []
        self.failed = []

    def check_rate(self, *args, **kwargs):
        pass

    def begin_turn(self, *args):
        return None

    def history(self, *args, **kwargs):
        return []

    def complete_turn(self, *args):
        response = args[2]
        assert isinstance(response, finalization.FinalPayload)
        self.canonical = response.verified_copy()
        # Exercise the actual repository serializer against an isolated SQL sink.
        repository.Repository().complete_turn(*args)

    def fail_turn(self, *args, **kwargs):
        self.failed.append(args)

    @contextmanager
    def connection(self):
        def execute(sql, args):
            self.sql.append((sql, args))
            if "UPDATE support_turns SET state='completed'" in sql:
                self.persisted = deepcopy(args[0].obj)
            return SimpleNamespace(fetchone=lambda: (1,))

        yield SimpleNamespace(execute=execute)


@pytest.mark.parametrize("mode", ["extractive", "generated"])
def test_canonical_answer_matches_evaluation_safety_api_and_persistence(
    mode, detector, monkeypatch, make_client
):
    monkeypatch.setenv("ANSWER_MODE", mode)
    monkeypatch.setenv("PERSISTENCE_ENABLED", "1")
    monkeypatch.setenv("SERVICE_API_KEY", "synthetic-service-key")
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    get_settings.cache_clear()
    repo = IsolatedRepository()
    monkeypatch.setattr(http_api, "get_repository", lambda: repo)
    monkeypatch.setattr(repository, "connection", repo.connection)
    monkeypatch.setattr(loop.ticketing, "existing_ticket", lambda *a, **k: None)
    monkeypatch.setattr(loop.refusal, "check_input", lambda _: SimpleNamespace(refuse=False))
    source = approved_source(chunk=POLICY + " Contact jane@example.com.")
    draft = "Use Billing then Cancel. Your email is jane@example.com. password=secret123"
    fake = make_client(
        [
            FakeResponse(
                content=[ToolUseBlock("kb", "knowledge_base", {"query": "cancel"})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[TextBlock(draft)], stop_reason="end_turn"),
        ]
    )
    monkeypatch.setattr(loop, "get_client", lambda: fake)
    monkeypatch.setattr(
        loop,
        "dispatch",
        lambda *_: SimpleNamespace(
            text=source.chunk,
            citations=[source],
            is_handoff=False,
            ticket_id=None,
        ),
    )
    scored, safety_inputs, returned_traces, prepared_payloads = [], [], [], []
    real_prepare = loop.prepare_response

    def prepare(trace, decision):
        real_prepare(trace, decision)
        prepared_payloads.append(trace._canonical_response.model_dump(mode="json"))

    monkeypatch.setattr(loop, "prepare_response", prepare)

    def score(**kwargs):
        assert prepared_payloads[0]["answer"] == kwargs["answer"]
        assert prepared_payloads[0]["citations"][0]["url"] == PUBLIC_URL
        scored.append(deepcopy(kwargs))
        return ConfidenceResult(score=1.0, reason="Supported", policy_consistent=True)

    def check(text):
        safety_inputs.append(text)
        return SimpleNamespace(refuse=False)

    monkeypatch.setattr(loop, "score_confidence", score)
    monkeypatch.setattr(loop.refusal, "check_response", check)
    real_run = loop.run_turn

    def run(**kwargs):
        trace = real_run(**kwargs)
        returned_traces.append(trace)
        # API/persistence may not invoke any later redaction on content.
        monkeypatch.setattr(detector, "redact", lambda *_a, **_k: pytest.fail("Late redaction"))
        return trace

    monkeypatch.setattr(server, "run_turn", run)
    request_id = str(uuid4())
    response = TestClient(server.app).post(
        "/chat",
        headers={
            "Authorization": "Bearer synthetic-service-key",
        },
        json={
            "conversation_id": str(uuid4()),
            "request_id": request_id,
            "message": "How do I cancel my subscription?",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == repo.canonical == repo.persisted
    assert not repo.failed
    assert payload["answer"] == scored[0]["answer"] == safety_inputs[0]
    assert payload["citations"] == [c.model_dump(mode="json") for c in scored[0]["citations"]]
    assert payload["citations"][0]["url"] == PUBLIC_URL
    assert PUBLIC_URL in safety_inputs[1]
    assert "jane@example.com" not in json.dumps(payload)
    assert "secret123" not in json.dumps(payload)
    if mode == "extractive":
        assert "the same day each month" in payload["answer"]
        assert payload["answer"] != draft
    else:
        assert payload["answer"].startswith("Use Billing then Cancel.")
    trace = returned_traces[0]
    record = next(s.attributes for s in trace.spans if s.name == "response_finalization")
    assert record["answer_mode"] == mode
    assert bool(record["replacement_reason"]) == (mode == "extractive")
    assert record["generated_draft"] != record["final_answer"] or mode == "generated"
    assert "jane@example.com" not in json.dumps(trace.model_dump(mode="json"))
    assert next(s for s in trace.spans if s.name == "final_response_safety").attributes["safe"]


@pytest.mark.parametrize("change", ["answer", "citations"])
def test_content_cannot_change_after_validation(change, monkeypatch, detector):
    trace = Trace(conversation_id="mutation", messages=[Message(role="user", content="Cancel?")])
    monkeypatch.setattr(loop, "score_confidence", lambda **_: ConfidenceResult(1, "Supported"))
    monkeypatch.setattr(loop.refusal, "check_response", lambda _: SimpleNamespace(refuse=False))
    decision = loop._finalize(trace, "Cancel from Billing.", [approved_source()], None, None)
    if change == "answer":
        decision.answer += " We guarantee a refund."
    else:
        decision.citations[0].url = "https://help.example.com/billing?token=private"
    with pytest.raises(finalization.FinalizationError):
        finalization.response_payload(trace)


def test_mutated_payload_is_rejected_before_persistence():
    payload = finalization.FinalPayload({"answer": "Safe", "citations": []})
    payload["answer"] = "Changed after validation"
    with pytest.raises(finalization.FinalizationError):
        repository.Repository().complete_turn("c", "r", payload, {}, "lease")


@pytest.mark.parametrize(
    "claim",
    [
        "If charged after cancelling, we'll refund it.",
        "All cancellations qualify for a full refund.",
        "Refunds arrive tomorrow.",
        "Refunds are issued as store credit.",
        "Cancellation is immediate and access ends now.",
        "Your subscription will renew again after cancellation.",
    ],
)
def test_policy_inconsistency_overrides_high_confidence_and_abstains(
    claim, monkeypatch, detector, make_client
):
    fake = make_client(
        [
            FakeResponse(
                content=[
                    TextBlock(
                        json.dumps(
                            {
                                "confidence": 1.0,
                                "reason": "A policy condition is broadened.",
                                "policy_consistent": False,
                            }
                        )
                    )
                ],
                stop_reason="end_turn",
            )
        ]
    )
    monkeypatch.setattr(confidence, "get_client", lambda: fake)
    trace = Trace(
        conversation_id="policy", messages=[Message(role="user", content="Billing policy?")]
    )
    decision = loop._finalize(trace, claim, [approved_source()], None, None)
    assert decision.confidence == 0
    assert "I don't know" in decision.answer
    assert not decision.citations and decision.ticket_id is None
    request = fake.messages.calls[0]
    assert claim in request["messages"][0]["content"]
    for condition in (
        "eligibility",
        "verification",
        "processing time",
        "original payment method",
        "cancellation effective dates",
        "renewal",
    ):
        assert condition in request["system"]


@pytest.mark.parametrize("verdict", [None, "true", 1])
def test_missing_or_invalid_policy_verdict_fails_closed(verdict, monkeypatch, make_client):
    fake = make_client(
        [
            FakeResponse(
                content=[
                    TextBlock(
                        json.dumps(
                            {
                                "confidence": 1.0,
                                "reason": "Supported",
                                "policy_consistent": verdict,
                            }
                        )
                    )
                ],
                stop_reason="end_turn",
            )
        ]
    )
    monkeypatch.setattr(confidence, "get_client", lambda: fake)
    result = confidence.score_confidence("Refund?", "A refund is guaranteed.", [approved_source()])
    assert result.score == 0 and not result.policy_consistent


def test_finalization_requires_explicit_policy_verdict(monkeypatch, detector):
    trace = Trace(conversation_id="no-verdict", messages=[Message(role="user", content="Refund?")])
    monkeypatch.setattr(
        loop, "score_confidence", lambda **_: SimpleNamespace(score=1, reason="High")
    )
    decision = loop._finalize(trace, "A refund is guaranteed.", [approved_source()], None, None)
    assert decision.confidence == 0
    assert "I don't know" in decision.answer
    assert not decision.citations


def test_missing_finalization_fails_closed_at_api(monkeypatch):
    monkeypatch.setattr(
        server,
        "run_turn",
        lambda **_: Trace(
            conversation_id="unvalidated",
            decision=Decision(
                type="answer",
                answer="Never checked",
                confidence=1,
                threshold=0.6,
            ),
        ),
    )
    response = TestClient(server.app).post(
        "/chat",
        json={
            "conversation_id": "unvalidated",
            "message": "Cancel?",
        },
    )
    assert response.status_code == 503
    assert "Never checked" not in response.text


def test_policy_verdict_accepts_supported_conditional_paraphrase(monkeypatch, make_client):
    answer = (
        "After verification, duplicate or post-cancellation charges are refunded to your "
        "original payment method in 5 to 7 business days."
    )
    fake = make_client(
        [
            FakeResponse(
                content=[
                    TextBlock(
                        json.dumps(
                            {
                                "confidence": 1,
                                "reason": "All conditions preserved.",
                                "policy_consistent": True,
                            }
                        )
                    )
                ],
                stop_reason="end_turn",
            )
        ]
    )
    monkeypatch.setattr(confidence, "get_client", lambda: fake)
    result = confidence.score_confidence("Refund policy?", answer, [approved_source()])
    assert result.score == 1 and result.policy_consistent


def test_mutation_during_evaluation_fails_closed(monkeypatch, detector):
    trace = Trace(conversation_id="race", messages=[Message(role="user", content="Cancel?")])

    def mutate(**kwargs):
        kwargs["citations"][0].chunk += " A refund is guaranteed."
        return ConfidenceResult(1, "Supported")

    monkeypatch.setattr(loop, "score_confidence", mutate)
    monkeypatch.setattr(loop.refusal, "check_response", lambda _: SimpleNamespace(refuse=False))
    with pytest.raises(finalization.FinalizationError):
        loop._finalize(trace, "Cancel from Billing.", [approved_source()], None, None)


@pytest.mark.parametrize("block_citations", [False, True])
def test_final_safety_failure_cannot_release_unchecked_replacement(
    block_citations, monkeypatch, detector
):
    trace = Trace(conversation_id="blocked", messages=[Message(role="user", content="Cancel?")])
    monkeypatch.setattr(loop, "_run_turn", lambda *a, **k: trace)
    trace.decision = Decision(
        type="answer",
        answer="Cancel from Billing.",
        citations=[approved_source()],
        confidence=1,
        threshold=0.6,
    )
    calls = []

    def check(text):
        calls.append(text)
        return SimpleNamespace(refuse=not block_citations or len(calls) == 2)

    monkeypatch.setattr(loop.refusal, "check_response", check)
    with pytest.raises(finalization.FinalizationError):
        loop.run_turn("blocked", "Cancel?")
    assert calls[0] == trace.decision.answer
    assert len(calls) == (2 if block_citations else 1)
