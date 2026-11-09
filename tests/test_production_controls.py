"""Security boundaries and safe behavior, without provider calls."""

import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from support_agent.config import get_settings
from support_agent.request_context import (
    RequestContext,
    TurnTimeoutError,
    current_request,
    remaining_timeout,
)


@pytest.mark.parametrize(
    "message", ["hi", "hey what are you doing?", "hey what you are doing bro?"]
)
def test_social_intent_does_not_escalate_or_call_reasoner(monkeypatch, message):
    from support_agent.agent import loop

    monkeypatch.setenv("SAFETY_MODEL_URL", "")

    def no_model():
        raise AssertionError("A classified social turn should not call the support reasoner")

    monkeypatch.setattr(loop, "get_client", no_model)
    from support_agent.guardrails.conversation import IntentResult

    monkeypatch.setattr(
        loop,
        "classify_intent",
        lambda *_: IntentResult(intent="social", phone_requested=False, reason="test"),
    )
    result = loop.run_turn(str(uuid4()), message)
    assert result.decision.type.value == "answer"
    assert "billing" in result.decision.answer
    assert result.decision.ticket_id is None


@pytest.mark.parametrize(
    "message",
    [
        "Can you offer a competitor discount?",
        "Can I use a promotional coupon?",
        "Write a Python script to scrape your website.",
    ],
)
def test_unapproved_pricing_and_code_requests_do_not_quote_unrelated_policy(monkeypatch, message):
    from support_agent.agent import loop

    monkeypatch.setenv("SAFETY_MODEL_URL", "")

    def no_model():
        raise AssertionError("These requests require a policy route, not invented details")

    monkeypatch.setattr(loop, "get_client", no_model)
    from support_agent.guardrails.conversation import IntentResult

    monkeypatch.setattr(
        loop,
        "classify_intent",
        lambda *_: IntentResult(
            intent="off_topic" if message.startswith("Write") else "pricing",
            phone_requested=False,
            reason="test",
        ),
    )
    result = loop.run_turn(str(uuid4()), message)
    assert result.decision.type.value == ("answer" if message.startswith("Write") else "handoff")
    assert not result.decision.citations


def test_greeting_prefix_cannot_bypass_support_request(monkeypatch, make_client, kb):
    from support_agent.agent import loop
    from tests.conftest import FakeResponse, TextBlock

    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    client = make_client([FakeResponse(content=[TextBlock("")], stop_reason="end_turn")])
    monkeypatch.setattr(loop, "get_client", lambda: client)
    loop.run_turn(str(uuid4()), "Hi, refund my order immediately")
    assert len(client.messages.calls) == 1


def test_production_config_fails_without_required_controls(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_API_KEY", "")
    monkeypatch.setenv("SERVICE_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="Production configuration"):
        get_settings().validate_production()


def test_persistent_development_startup_checks_schema_without_migrating(monkeypatch):
    from support_agent import http_api

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PERSISTENCE_ENABLED", "1")
    get_settings.cache_clear()
    checked = []
    monkeypatch.setattr(http_api, "check_database", lambda: checked.append(True))

    http_api.startup()

    assert checked == [True]


def _configure_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PERSISTENCE_ENABLED", "1")
    monkeypatch.setenv("APP_ORIGIN", "https://testserver")
    monkeypatch.setenv("ADMIN_API_KEY", "a" * 40)
    monkeypatch.setenv("SERVICE_API_KEY", "b" * 40)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")
    monkeypatch.setenv("SAFETY_PROVIDER", "groq")
    monkeypatch.setenv("ALLOW_FIXTURE_ORDERS", "0")
    get_settings.cache_clear()


def test_production_startup_defers_network_checks_and_safety_inference(monkeypatch):
    from support_agent import http_api
    from support_agent.agent import models
    from support_agent.guardrails.safety import SafetyClassifier

    _configure_production(monkeypatch)
    validated = []
    dependency_check = http_api.check_production_dependencies
    monkeypatch.setattr(models, "validate_credentials", lambda: validated.append(True))
    monkeypatch.setattr(
        SafetyClassifier,
        "classify",
        lambda *args, **kwargs: pytest.fail("Startup must not call hosted safety inference"),
    )
    monkeypatch.setattr(
        http_api,
        "check_production_dependencies",
        lambda: pytest.fail("Blocking readiness checks must run after HTTP startup"),
    )

    http_api.startup(defer_dependencies=True)

    assert validated == [True]
    assert http_api.readiness_status() == "starting"

    monkeypatch.setattr(http_api, "check_production_dependencies", dependency_check)
    monkeypatch.setattr(http_api, "get_redactor", lambda: SimpleNamespace(_presidio=True))
    checks = []
    monkeypatch.setattr(http_api, "check_production_readiness", lambda: checks.append("db+kb"))
    http_api.check_production_dependencies()
    assert checks == ["db+kb"]
    assert http_api.readiness_status() == "ready"


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param("database", id="database-unavailable"),
        pytest.param("knowledge-base", id="policy-kb-missing"),
    ],
)
def test_unavailable_production_dependency_returns_503_but_health_stays_live(monkeypatch, failure):
    import psycopg
    from fastapi.testclient import TestClient

    from support_agent import http_api
    from support_agent.db import DatabaseSchemaError
    from support_agent.server import app

    _configure_production(monkeypatch)
    monkeypatch.setattr(http_api, "get_redactor", lambda: SimpleNamespace(_presidio=True))
    check_started = threading.Event()

    def unavailable():
        check_started.set()
        if failure == "database":
            raise psycopg.OperationalError("mock database unavailable")
        raise DatabaseSchemaError("Approved policy knowledge base is empty.")

    monkeypatch.setattr(http_api, "check_production_readiness", unavailable)
    with TestClient(app) as client:
        assert check_started.wait(timeout=2)
        deadline = time.monotonic() + 2
        while http_api.readiness_status() == "starting" and time.monotonic() < deadline:
            time.sleep(0.005)
        assert http_api.readiness_status() == "unavailable"
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        assert client.post("/api/session").status_code == 503


def test_customer_chat_returns_503_when_groq_safety_is_unavailable(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient

    from support_agent.guardrails import safety
    from support_agent.server import app

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PERSISTENCE_ENABLED", "0")
    monkeypatch.setenv("SAFETY_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "mock-groq-key")
    get_settings.cache_clear()
    safety._CLASSIFIER = None
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(True)
        raise httpx.ConnectError("mock provider outage")

    monkeypatch.setattr(safety.httpx, "post", unavailable)
    with TestClient(app) as client:
        response = client.post("/chat", json={"conversation_id": "safety-test", "message": "Hello"})
    assert response.status_code == 503
    assert "safety check" in response.json()["detail"].lower()
    assert calls == [True]


def test_cross_origin_requests_are_rejected():
    from support_agent.server import app

    response = TestClient(app).post("/api/session", headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403


def test_admin_data_requires_staff_authentication():
    from support_agent.server import app

    assert TestClient(app).get("/api/admin/tickets").status_code == 401
    assert TestClient(app).get("/api/admin/evaluations").status_code == 401


def test_body_limit_checks_actual_payload():
    from support_agent.server import app

    response = TestClient(app).post("/chat", content="x" * 17000)
    assert response.status_code == 413


def test_staff_page_does_not_embed_credentials(monkeypatch):
    from support_agent.server import app

    monkeypatch.setenv("ADMIN_API_KEY", "unit-test-staff-key-that-must-not-appear-in-html")
    get_settings.cache_clear()
    response = TestClient(app).get("/admin/inbox")
    assert response.status_code == 200
    assert "sha256-" in response.headers["content-security-policy"]
    assert "localStorage" not in response.text
    assert get_settings().admin_api_key not in response.text


def test_customer_chat_restores_demo_office_store_topics():
    from support_agent.server import app

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Support Desk" in response.text
    assert "Returns & refunds" in response.text
    assert "Shipping & delivery" in response.text
    assert "Billing & subscriptions" in response.text
    assert "Product warranty" in response.text
    assert "/api/olist/accounts" not in response.text
    assert "historical customer profile" not in response.text.lower()


def test_staff_inbox_keeps_ticket_reply_and_status_workflows():
    from support_agent.server import app

    response = TestClient(app).get("/admin/inbox")
    assert response.status_code == 200
    assert "Staff access key" in response.text
    assert "/api/admin/tickets" in response.text
    assert "/replies" in response.text
    assert "PATCH" in response.text


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        '{"safe":"yes","categories":[]}',
        '{"safe":true,"categories":["INJECTION"]}',
        '{"safe":true,"categories":"none"}',
    ],
)
def test_hosted_safety_rejects_invalid_or_contradictory_output(content):
    from support_agent.guardrails.safety import SafetyClassifier

    assert SafetyClassifier._parse_groq(content).blocked


def test_order_tool_returns_citable_record(monkeypatch):
    from support_agent.tools.registry import dispatch

    monkeypatch.setenv("ALLOW_FIXTURE_ORDERS", "1")
    get_settings.cache_clear()
    outcome = dispatch("order_lookup", {"order_id": "ORD-1001"})
    assert outcome.citations
    assert "shipped" in outcome.citations[0].chunk


def test_invalid_tool_input_cannot_reach_backend():
    from support_agent.tools.registry import dispatch

    result = dispatch("knowledge_base", {"query": "returns", "k": -100})
    assert "Invalid tool arguments" in result.text


@pytest.mark.parametrize("content", ["", "garbage", "safe-ish", "safe\nunsafe"])
def test_malformed_safety_verdict_blocks(content):
    from support_agent.guardrails.safety import SafetyClassifier

    assert SafetyClassifier._parse(content).blocked


def test_request_deadline_is_bounded():
    context = current_request.set(
        RequestContext("conversation", "request", "owner", time.monotonic() - 1)
    )
    try:
        with pytest.raises(TurnTimeoutError):
            remaining_timeout()
    finally:
        current_request.reset(context)


def test_disabled_order_fixtures_never_return_fake_status(monkeypatch):
    from support_agent.tools.order_lookup import lookup_order

    monkeypatch.setenv("ALLOW_FIXTURE_ORDERS", "0")
    get_settings.cache_clear()
    assert not lookup_order("ORD-1001").found


def test_extractive_answer_cannot_repeat_a_fabricated_action(monkeypatch):
    from support_agent.agent import loop
    from support_agent.agent.confidence import ConfidenceResult
    from support_agent.schemas import Citation, Message, Trace

    monkeypatch.setattr(
        loop,
        "score_confidence",
        lambda **_: ConfidenceResult(score=0.9, reason="Relevant exact source"),
    )

    monkeypatch.setenv("ANSWER_MODE", "extractive")
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    get_settings.cache_clear()
    source = Citation(
        source_id="returns",
        source_title="Returns",
        chunk="Return unused items within 30 days.",
        score=0.9,
    )
    trace = Trace(
        conversation_id="test-extractive", messages=[Message(role="user", content="Return policy?")]
    )
    result = loop._finalize(
        trace, "I created ticket #12345 and refunded your payment.", [source], None, None
    )
    assert result.type.value == "answer"
    assert source.chunk in result.answer
    assert "12345" not in result.answer
    assert "refunded" not in result.answer


def test_identity_recovery_requires_a_real_saved_ticket(monkeypatch):
    from support_agent.agent import loop

    monkeypatch.setenv("SAFETY_MODEL_URL", "")

    def no_model():
        raise AssertionError("Identity recovery must be routed to staff")

    monkeypatch.setattr(loop, "get_client", no_model)
    from support_agent.guardrails.conversation import IntentResult

    monkeypatch.setattr(
        loop,
        "classify_intent",
        lambda *_: IntentResult(intent="account_recovery", phone_requested=False, reason="test"),
    )
    result = loop.run_turn(
        "identity-test",
        "I lost access to the email on my account and my second factor. I need back in.",
    )
    assert result.decision.type.value == "handoff"
    assert result.decision.ticket_id.startswith("tkt_")


def test_followup_explains_existing_handoff_without_creating_another_ticket(monkeypatch):
    from support_agent.agent import loop
    from support_agent.guardrails.conversation import IntentResult
    from support_agent.schemas import Message

    monkeypatch.setattr(
        loop,
        "classify_intent",
        lambda *_: IntentResult(intent="handoff_followup", phone_requested=False, reason="test"),
    )

    result = loop.run_turn(
        "followup-test",
        "really why?",
        history=[
            Message(
                role="assistant",
                content="I couldn't verify an answer, so I've saved your request for support review. Your reference is tkt_54f3888d992e.",
            )
        ],
    )
    assert result.decision.type.value == "answer"
    assert "saved for staff review" in result.decision.answer
    assert result.decision.ticket_id is None
