"""Verify the running local app without printing access keys or session tokens."""

import argparse
import json
import time
from uuid import uuid4

import httpx

from support_agent.config import get_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        action="store_true",
        help="Also make a real support request; free quota may require a retry wait",
    )
    args = parser.parse_args()
    settings = get_settings()
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=210, trust_env=False) as client:
        for attempt in range(30):
            try:
                client.get("/readyz").raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 29:
                    raise
                time.sleep(1)
        page = client.get("/")
        page.raise_for_status()
        assert "sha256-" in page.headers["content-security-policy"]
        response = client.post("/api/session")
        response.raise_for_status()
        assert "HttpOnly" in response.headers.get("set-cookie", "")
        conversation = client.post("/api/conversations")
        conversation.raise_for_status()
        conversation_id = conversation.json()["conversation_id"]
        payload = {
            "conversation_id": conversation_id,
            "request_id": str(uuid4()),
            "message": "hey what you are doing bro?",
        }
        greeting = client.post("/chat", json=payload)
        greeting.raise_for_status()
        assert not greeting.json()["handoff"]
        replay = client.post("/chat", json=payload)
        assert replay.json() == greeting.json()
        history = client.get("/api/conversations/" + conversation_id)
        history.raise_for_status()
        assert len(history.json()["messages"]) == 2
        assert (
            httpx.get(
                "http://127.0.0.1:8001/api/conversations/" + conversation_id, trust_env=False
            ).status_code
            == 401
        )
        assert client.get("/api/admin/tickets").status_code == 401
        staff = client.get(
            "/api/admin/activity", headers={"Authorization": "Bearer " + settings.admin_api_key}
        )
        staff.raise_for_status()
        assert any(turn["request_id"] == payload["request_id"] for turn in staff.json())
        factual = None
        if args.model:
            query = {
                "conversation_id": conversation_id,
                "request_id": str(uuid4()),
                "message": "What is your return policy?",
            }
            for attempt in range(3):
                result = client.post("/chat", json=query)
                if result.status_code != 429 or attempt == 2:
                    break
                print("Waiting 60 seconds for free provider quota.", flush=True)
                time.sleep(60)
            result.raise_for_status()
            factual = result.json()
            assert not factual["handoff"]
            assert factual["citations"][0]["source_id"] == "returns-policy"
            assert factual["citations"][0]["chunk"] in factual["answer"]
            assert "30 days" in factual["answer"]
        print(
            json.dumps(
                {
                    "frontend": "ok",
                    "session_cookie": "HttpOnly",
                    "database_history": "saved",
                    "retry": "deduplicated",
                    "staff_auth": "enforced",
                    "greeting": greeting.json()["answer"],
                    "trace_id": greeting.json()["langfuse_trace_id"],
                    "factual_answer": "verified exact source excerpt"
                    if factual
                    else "not requested",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
