"""Verify local scope redirects, persistence, and absence of accidental tickets."""

import argparse
import json
import time
from uuid import uuid4

import httpx

from support_agent.config import get_settings
from support_agent.db import close_pool
from support_agent.repository import get_repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--greeting-only", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    headers = {"Authorization": "Bearer " + settings.admin_api_key}
    cases = []
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=60, trust_env=False) as client:
        for attempt in range(30):
            try:
                client.get("/readyz").raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 29:
                    raise
                time.sleep(1)
        client.post("/api/session").raise_for_status()
        response = client.post("/api/conversations")
        response.raise_for_status()
        conversation_id = response.json()["conversation_id"]
        messages = (
            ["hey bro what you are doing/"]
            if args.greeting_only
            else [
                "hey bro what you are doing/",
                "fuck you bro",
                "really do you think this will happen?",
                "tell me a joke",
                "What is the weather today?",
            ]
        )
        for message in messages:
            response = client.post(
                "/chat",
                json={
                    "conversation_id": conversation_id,
                    "request_id": str(uuid4()),
                    "message": message,
                },
            )
            response.raise_for_status()
            data = response.json()
            assert not data["handoff"] and data["ticket_id"] is None
            assert not data["citations"]
            if args.greeting_only:
                assert "What can I help you with?" in data["answer"]
            cases.append({"message": message, "answer": data["answer"], "passed": True})
        history = client.get("/api/conversations/" + conversation_id)
        history.raise_for_status()
        assert len(history.json()["messages"]) == 2 * len(messages)
        tickets = client.get("/api/admin/tickets", headers=headers)
        tickets.raise_for_status()
        assert not any(str(t["conversation_id"]) == conversation_id for t in tickets.json())
        activity = client.get("/api/admin/activity", headers=headers)
        activity.raise_for_status()
        turns = [t for t in activity.json() if str(t["conversation_id"]) == conversation_id]
        assert len(turns) == len(messages)
        assert all(
            any(s["name"] == "conversation_scope" for s in t["trace"]["spans"]) for t in turns
        )
    report = {"cases": cases, "passed": len(cases), "history_saved": True, "tickets_created": 0}
    identifier = get_repository().save_eval("conversation-scope-regression", report)
    close_pool()
    print(
        json.dumps({"passed": len(cases), "tickets_created": 0, "database_report_id": identifier})
    )


if __name__ == "__main__":
    main()
