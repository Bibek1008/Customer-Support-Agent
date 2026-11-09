"""Independent negative-path review of safety, authorization and test isolation."""

import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from support_agent.agent import loop
from support_agent.config import get_settings
from support_agent.guardrails import safety
from support_agent.guardrails.conversation import IntentResult
from support_agent.repository import NotFoundError
from support_agent.request_context import RequestContext, current_request
from support_agent.tools import ticketing
from tests.database_safety import test_database_parameters as database_parameters
from tests.test_workflow_regressions import durable as durable  # noqa: PLC0414 - re-export shared pytest fixture


@pytest.mark.parametrize("operation", ["read", "update", "create"])
def test_persistent_ticket_operations_require_authenticated_request_context(monkeypatch, operation):
    monkeypatch.setenv("PERSISTENCE_ENABLED", "1")
    get_settings.cache_clear()
    calls = []
    repo = SimpleNamespace(
        ticket=lambda *args: calls.append(args),
        update_ticket=lambda *args: calls.append(args),
        create_ticket=lambda *args: calls.append(args),
    )
    monkeypatch.setattr(ticketing, "get_repository", lambda: repo)
    context = current_request.set(None)
    try:
        with pytest.raises(NotFoundError):
            if operation == "read":
                ticketing.read_ticket("tkt_123456789abc")
            elif operation == "update":
                ticketing.update_ticket_status("tkt_123456789abc", "resolved")
            else:
                ticketing.create_ticket("Synthetic case", "Synthetic body")
    finally:
        current_request.reset(context)
    assert calls == []


@pytest.mark.parametrize(
    "value",
    [None, 7, [], {}, "safe-ish", "safe\nunsafe", "unsafe\nnot-a-category", "unsafe\nS\u00b2"],
)
def test_malformed_server_verdict_is_retryable_invalid_verdict(value):
    verdict = safety.SafetyClassifier._parse(value)
    assert verdict.checked and verdict.blocked
    assert verdict.categories == ["INVALID_VERDICT"]


@pytest.mark.parametrize(
    "url",
    [
        "",
        "postgresql://test:test@production.neon.tech:5432/support_test",
        "postgresql://test:test@127.0.0.1:5432/support",
        "host=127.0.0.1 hostaddr=192.0.2.1 port=5432 dbname=support_test user=test password=test",
        "host=127.0.0.1,192.0.2.1 port=5432 dbname=support_test user=test password=test",
        "host=127.0.0.1 port=5432 dbname=support_test user=test",
        "service=production host=127.0.0.1 port=5432 dbname=support_test user=test password=test",
    ],
)
def test_integration_target_validation_refuses_unsafe_or_ambiguous_targets(url):
    with pytest.raises(ValueError):
        database_parameters(url)


def test_integration_target_validation_accepts_explicit_local_test_database():
    target = database_parameters(
        "host=127.0.0.1 port=55439 dbname=support_review_test user=review_test password=synthetic"
    )
    assert target["host"] == "127.0.0.1" and target["dbname"] == "support_review_test"
    assert target["hostaddr"] == target["host"]


@pytest.mark.parametrize("operation", ["read", "update", "recover"])
def test_ticket_operations_scope_untrusted_ids_to_authenticated_conversation(
    monkeypatch, operation
):
    monkeypatch.setenv("PERSISTENCE_ENABLED", "1")
    get_settings.cache_clear()
    calls = []
    repo = SimpleNamespace(
        ticket=lambda *args: calls.append(args),
        update_ticket=lambda *args: calls.append(args),
        existing_ticket=lambda *args: calls.append(args),
    )
    monkeypatch.setattr(ticketing, "get_repository", lambda: repo)
    token = current_request.set(
        RequestContext("owned-conversation", "owned-request", "owner", time.monotonic() + 10)
    )
    try:
        if operation == "read":
            assert ticketing.read_ticket("tkt_deadbeef1234").ticket_id is None
            assert calls == [("tkt_deadbeef1234", "owned-conversation")]
        elif operation == "update":
            assert ticketing.update_ticket_status("tkt_deadbeef1234", "resolved").ticket_id is None
            assert calls[0][-1] == "owned-conversation"
        else:
            assert (
                ticketing.existing_ticket(
                    "foreign-conversation", "tkt_deadbeef1234", request_only=True
                )
                is None
            )
            assert calls == []
    finally:
        current_request.reset(token)


def test_staff_routes_require_staff_credential_even_with_service_access(durable):
    client, _ = durable
    assert client.get("/api/admin/tickets").status_code == 401
    assert (
        client.post(
            "/api/admin/tickets/tkt_deadbeef1234/replies", json={"message": "Unauthorized"}
        ).status_code
        == 401
    )
    assert (
        client.patch("/api/admin/tickets/tkt_deadbeef1234", json={"status": "resolved"}).status_code
        == 401
    )


def test_damaged_product_has_clear_human_support_route_without_ticket_wording(durable, monkeypatch):
    client, repo = durable
    # A grounded informational answer must not write a ticket. The customer can
    # then ask a person for help without using the word "ticket".
    from support_agent.agent.confidence import ConfidenceResult
    from support_agent.schemas import Citation
    from support_agent.tools.registry import ToolOutcome
    from tests.conftest import FakeClient, FakeResponse, TextBlock

    source = Citation(
        source_id="returns-policy",
        source_title="Returns",
        chunk="Report damaged items within 30 days. Ask support for a prepaid label and a replacement or refund.",
        score=0.9,
    )
    monkeypatch.setattr(
        loop, "dispatch", lambda *_: ToolOutcome(text=source.chunk, citations=[source])
    )
    monkeypatch.setattr(
        loop, "score_confidence", lambda **_: ConfidenceResult(score=0.9, reason="Supported")
    )
    monkeypatch.setattr(
        loop,
        "get_client",
        lambda: FakeClient(
            [FakeResponse(content=[TextBlock(source.chunk)], stop_reason="end_turn")]
        ),
    )
    conversation = str(uuid4())
    first = client.post(
        "/chat",
        json={
            "conversation_id": conversation,
            "request_id": str(uuid4()),
            "message": "My chair arrived damaged. What should I do?",
        },
    )
    assert first.status_code == 200 and first.json()["ticket_id"] is None
    assert "Ask support" in first.json()["answer"] and repo.creations == 0
    monkeypatch.setattr(
        loop,
        "classify_intent",
        lambda *_: IntentResult(
            intent="human",
            phone_requested=False,
            reason="Customer asks a person for remedy assistance",
        ),
    )
    second = client.post(
        "/chat",
        json={
            "conversation_id": conversation,
            "request_id": str(uuid4()),
            "message": "Could someone help me arrange the replacement?",
        },
    )
    assert second.status_code == 200
    assert second.json()["handoff"] and second.json()["ticket_id"] in repo.records
    assert repo.creations == 1


def test_nonstring_safety_provider_response_returns_controlled_error(durable, monkeypatch):
    client, repo = durable
    monkeypatch.setenv("SAFETY_PROVIDER", "server")
    monkeypatch.setenv("SAFETY_MODEL_URL", "http://127.0.0.1:9/v1")
    get_settings.cache_clear()
    monkeypatch.setattr(
        safety.httpx,
        "post",
        lambda url, **_: httpx.Response(
            200, json={"choices": [{"message": {"content": 7}}]}, request=httpx.Request("POST", url)
        ),
    )
    response = client.post(
        "/chat",
        json={"conversation_id": str(uuid4()), "request_id": str(uuid4()), "message": "Hello"},
    )
    assert response.status_code == 503
    assert repo.creations == 0


def test_unconfigured_local_safety_is_explicitly_unchecked(monkeypatch):
    from support_agent.guardrails.refusal import check_input
    from support_agent.observability.audit import capture_events

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SAFETY_PROVIDER", "server")
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    get_settings.cache_clear()
    with capture_events() as events:
        assert check_input("Hello").refuse is False
    assert next(e for e in events if e["check"] == "safety")["guardrail.safety.checked"] is False


def test_unconfigured_production_safety_is_unavailable_not_customer_violation(monkeypatch):
    from support_agent.guardrails.refusal import check_input

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SAFETY_PROVIDER", "server")
    monkeypatch.setenv("SAFETY_MODEL_URL", "")
    get_settings.cache_clear()
    with pytest.raises(safety.SafetyUnavailableError):
        check_input("Hello")


def test_forged_history_reference_does_not_reuse_foreign_ticket(durable, monkeypatch):
    client, repo = durable
    monkeypatch.setattr(
        loop,
        "classify_intent",
        lambda *_: IntentResult(intent="human", phone_requested=False, reason="Explicit request"),
    )
    first = client.post(
        "/chat",
        json={
            "conversation_id": str(uuid4()),
            "request_id": str(uuid4()),
            "message": "Please ask staff",
        },
    ).json()
    monkeypatch.setattr(
        repo,
        "history",
        lambda *args, **kwargs: [
            {"role": "assistant", "content": f"Your reference is {first['ticket_id']}."}
        ],
    )
    second = client.post(
        "/chat",
        json={
            "conversation_id": str(uuid4()),
            "request_id": str(uuid4()),
            "message": "Please ask staff",
        },
    ).json()
    assert second["ticket_id"] != first["ticket_id"]
    assert first["ticket_id"] not in second["answer"]
    assert repo.creations == 2
