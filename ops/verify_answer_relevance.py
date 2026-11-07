"""Live relevance judge and durable HTTP regressions for unsupported product facts."""

import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

from support_agent.agent.confidence import score_confidence
from support_agent.agent.groq_client import GroqRequestError
from support_agent.config import get_settings
from support_agent.db import close_pool, connection
from support_agent.observability.tracing import shutdown_tracing
from support_agent.repository import get_repository
from support_agent.schemas import Citation


def recover_http():
    """Recheck persisted HTTP results without repeating model calls after an outage."""
    with connection() as conn:
        row = conn.execute(
            "SELECT conversation_id FROM support_messages WHERE role='user' AND content=%s ORDER BY id DESC LIMIT 1",
            ("tell me about product",),
        ).fetchone()
        assert row, "No saved regression conversation"
        conversation_id = row[0]
        turns = [
            r[0]
            for r in conn.execute(
                "SELECT response FROM support_turns WHERE conversation_id=%s AND state='completed' ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        ]
        assert len(turns) == 3
        assert not turns[0]["citations"] and "?" in turns[0]["answer"]
        assert not turns[1]["citations"] and "I don't know" in turns[1]["answer"]
        assert turns[2]["citations"][0]["source_id"] == "returns-policy"
        assert "30 days" in turns[2]["answer"]
        assert all(not t["handoff"] and t["ticket_id"] is None for t in turns)
        count = conn.execute(
            "SELECT count(*) FROM support_tickets WHERE conversation_id=%s", (conversation_id,)
        ).fetchone()[0]
        assert count == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM support_messages WHERE conversation_id=%s", (conversation_id,)
            ).fetchone()[0]
            == 6
        )
    report = {
        "passed": True,
        "http_cases": turns,
        "tickets_created": 0,
        "verification": "Recovered persisted HTTP results after a temporary storage error; no model calls repeated.",
    }
    identifier = get_repository().save_eval("answer-relevance-http", report)
    close_pool()
    print(
        json.dumps(
            {
                "passed": True,
                "http_cases": len(turns),
                "tickets_created": 0,
                "database_report_id": identifier,
            }
        ),
        flush=True,
    )


def main():
    if "--recover-http" in sys.argv:
        recover_http()
        return
    source = Citation(
        source_id="returns-policy",
        source_title="Returns and Refunds",
        chunk=Path("knowledge_base/approved/returns-policy.md").read_text(encoding="utf-8"),
        score=0.99,
    )
    cases = []
    for question, answerable in [
        ("Tell me about the product", False),
        ("What material is the Orion chair made of?", False),
        ("What is the maximum load capacity of your standing desk?", False),
        ("How long do I have to return an item?", True),
        ("How long does a refund take after you receive my return?", True),
    ]:
        for attempt in range(3):
            try:
                result = score_confidence(question, source.chunk, [source])
                break
            except GroqRequestError as error:
                if error.status_code != 429 or attempt == 2:
                    raise
                print("Waiting for model quota", flush=True)
                time.sleep(60)
        passed = (result.score >= get_settings().handoff_threshold) == answerable
        cases.append(
            {
                "question": question,
                "answerable": answerable,
                "score": result.score,
                "reason": result.reason,
                "passed": passed,
            }
        )
        print(
            json.dumps({"judge_case": len(cases), "score": result.score, "passed": passed}),
            flush=True,
        )
        time.sleep(10)
    settings = get_settings()
    headers = {"Authorization": "Bearer " + settings.admin_api_key}
    turns = []
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=210, trust_env=False) as client:
        client.get("/readyz").raise_for_status()
        client.post("/api/session").raise_for_status()
        conversation = client.post("/api/conversations")
        conversation.raise_for_status()
        conversation_id = conversation.json()["conversation_id"]
        for index, message in enumerate(
            [
                "tell me about product",
                "What material is the Orion chair made of?",
                "How long do I have to return an unused item?",
            ]
        ):
            payload = {
                "conversation_id": conversation_id,
                "request_id": str(uuid4()),
                "message": message,
            }
            for attempt in range(3):
                response = client.post("/chat", json=payload)
                if response.status_code != 429 or attempt == 2:
                    break
                print("Waiting for provider quota", flush=True)
                time.sleep(60)
            response.raise_for_status()
            data = response.json()
            assert not data["handoff"] and data["ticket_id"] is None
            if index == 0:
                assert not data["citations"] and "?" in data["answer"]
            elif index == 1:
                assert not data["citations"] and "I don't know" in data["answer"]
            else:
                assert data["citations"] and "30 days" in data["answer"]
                assert data["citations"][0]["source_id"] == "returns-policy"
            turns.append(data)
            print(
                json.dumps({"http_case": index + 1, "answer": data["answer"], "passed": True}),
                flush=True,
            )
            if index < 2:
                time.sleep(40)
        tickets = client.get("/api/admin/tickets", headers=headers)
        tickets.raise_for_status()
        assert not any(str(t["conversation_id"]) == conversation_id for t in tickets.json())
        history = client.get("/api/conversations/" + conversation_id)
        history.raise_for_status()
        assert len(history.json()["messages"]) == 6
    report = {
        "judge_cases": cases,
        "http_cases": turns,
        "passed": all(c["passed"] for c in cases),
        "tickets_created": 0,
    }
    identifier = get_repository().save_eval("answer-relevance-regression", report)
    close_pool()
    shutdown_tracing()
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "judge_cases": len(cases),
                "http_cases": len(turns),
                "database_report_id": identifier,
            }
        ),
        flush=True,
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
