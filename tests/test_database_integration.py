"""Real PostgreSQL tests. Opt in with SUPPORT_TEST_DATABASE=1 against a test database.

Tests retain clearly labelled synthetic records; they never truncate existing data.
"""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.environ.get("SUPPORT_TEST_DATABASE") != "1",
    reason="Requires an explicitly enabled PostgreSQL integration database",
)


@pytest.fixture
def database(monkeypatch):
    from support_agent.config import get_settings
    from support_agent.db import close_pool, migrate

    monkeypatch.setenv("PERSISTENCE_ENABLED", "1")
    monkeypatch.setenv("ADMIN_API_KEY", "integration-staff-secret-with-at-least-32-characters")
    monkeypatch.setenv("SERVICE_API_KEY", "integration-service-secret-with-at-least-32-characters")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1000")
    get_settings.cache_clear()
    migrate()
    yield
    close_pool()


def test_durable_chat_isolation_replay_history_and_staff_reply(database, monkeypatch):
    from support_agent import server
    from support_agent.db import close_pool, connection
    from support_agent.schemas import Decision, DecisionType, Message, Trace
    from support_agent.tools.handoff import escalate_to_human

    calls = []

    def agent(conversation_id, user_message, customer_id, history):
        calls.append(history)
        messages = [*history, Message(role="user", content=user_message)]
        if user_message == "Please ask a human":
            handoff = escalate_to_human("Synthetic integration case", messages, 0)
            decision = Decision(
                type=DecisionType.HANDOFF,
                answer=handoff.text,
                confidence=0,
                threshold=0.6,
                ticket_id=handoff.ticket_id,
            )
        else:
            decision = Decision(
                type=DecisionType.ANSWER, answer="Synthetic answer", confidence=0.9, threshold=0.6
            )
        return Trace(conversation_id=conversation_id, messages=messages, decision=decision)

    monkeypatch.setattr(server, "run_turn", agent)
    a, b = TestClient(server.app), TestClient(server.app)
    assert a.post("/api/session").status_code == 200
    assert b.post("/api/session").status_code == 200
    conversation = a.post("/api/conversations").json()["conversation_id"]
    payload = {
        "conversation_id": conversation,
        "request_id": str(uuid4()),
        "message": "Synthetic test, email test@example.com",
    }
    response = a.post("/chat", json=payload)
    assert response.status_code == 200, response.text
    assert a.post("/chat", json=payload).json() == response.json()
    assert len(calls) == 1
    assert a.post("/chat", json={**payload, "message": "Different message"}).status_code == 409
    assert b.get("/api/conversations/" + conversation).status_code == 404
    assert b.post("/chat", json={**payload, "request_id": str(uuid4())}).status_code == 404
    history = a.get("/api/conversations/" + conversation).json()["messages"]
    assert len(history) == 2
    assert "test@example.com" not in str(history)
    assert "<EMAIL_ADDRESS>" in history[0]["content"]
    # Recreate the connection pool to prove this is database state, not a singleton cache.
    close_pool()
    assert len(a.get("/api/conversations/" + conversation).json()["messages"]) == 2
    handoff = a.post(
        "/chat",
        json={
            "conversation_id": conversation,
            "request_id": str(uuid4()),
            "message": "Please ask a human",
        },
    )
    assert handoff.status_code == 200, handoff.text
    assert len(calls[-1]) == 2
    ticket_id = handoff.json()["ticket_id"]
    assert ticket_id
    headers = {"Authorization": "Bearer integration-staff-secret-with-at-least-32-characters"}
    tickets = a.get("/api/admin/tickets", headers=headers).json()
    assert any(t["id"] == ticket_id for t in tickets)
    assert (
        a.post(
            f"/api/admin/tickets/{ticket_id}/replies",
            headers=headers,
            json={"message": "Synthetic staff reply"},
        ).status_code
        == 200
    )
    assert a.get("/api/conversations/" + conversation).json()["messages"][-1]["role"] == "staff"
    assert (
        a.patch(
            f"/api/admin/tickets/{ticket_id}", headers=headers, json={"status": "resolved"}
        ).status_code
        == 200
    )
    with connection() as conn:
        trace = conn.execute(
            "SELECT trace FROM support_turns WHERE request_id=%s", (payload["request_id"],)
        ).fetchone()[0]
        assert "test@example.com" not in str(trace)


def test_leases_prevent_concurrent_turns_and_stale_completion(database):
    from support_agent.db import connection
    from support_agent.repository import ConflictError, Repository

    repo = Repository()
    owner = "synthetic:" + str(uuid4())
    conversation = repo.create_conversation(owner)
    first, second = str(uuid4()), str(uuid4())
    repo.begin_turn(conversation, owner, first, "Synthetic message", "fingerprint", "lease-one")
    with pytest.raises(ConflictError):
        repo.begin_turn(
            conversation, owner, second, "Another message", "fingerprint-two", "lease-two"
        )
    with connection() as conn:
        conn.execute(
            "UPDATE support_conversations SET lease_until=now()-interval '1 second' WHERE id=%s",
            (conversation,),
        )
    repo.begin_turn(conversation, owner, first, "Synthetic message", "fingerprint", "lease-two")
    with pytest.raises(ConflictError):
        repo.complete_turn(conversation, first, {"answer": "Stale answer"}, {}, "lease-one")
    repo.fail_turn(conversation, first, "old-worker", "lease-one")
    repo.complete_turn(conversation, first, {"answer": "Current answer"}, {}, "lease-two")
    assert repo.history(conversation, owner)[-1]["content"] == "Current answer"


def test_rate_limit_and_eval_results_persist(database):
    from support_agent.repository import RateLimitError, Repository

    repo = Repository()
    owner = "rate-test:" + str(uuid4())
    repo.check_rate(owner, limit=1)
    with pytest.raises(RateLimitError):
        repo.check_rate(owner, limit=1)
    identifier = repo.save_eval(
        "synthetic-integration", {"note": "Synthetic database test, no model score"}
    )
    assert any(e["id"] == identifier for e in Repository().evaluations())
