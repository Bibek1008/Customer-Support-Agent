"""Check the reported human/phone request through the durable HTTP frontend API."""

import json
import time
from uuid import uuid4

import httpx

from support_agent.config import get_settings
from support_agent.db import close_pool
from support_agent.repository import get_repository


def main():
    settings = get_settings()
    headers = {"Authorization": "Bearer " + settings.admin_api_key}
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=210, trust_env=False) as client:
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
        results = []
        for message in [
            "can you connect with human agent i want to talk before that can you provide their number?",
            "Do you seriously think anyone will get back to me?",
        ]:
            request = {
                "conversation_id": conversation_id,
                "request_id": str(uuid4()),
                "message": message,
            }
            for attempt in range(3):
                response = client.post("/chat", json=request)
                if response.status_code != 429 or attempt == 2:
                    break
                print("Waiting for provider quota", flush=True)
                time.sleep(60)
            response.raise_for_status()
            results.append(response.json())
            print(json.dumps({"turn": len(results), "answer": results[-1]["answer"]}), flush=True)
        first, followup = results
        assert first["handoff"] and first["ticket_id"]
        assert "don't have a verified support phone number" in first["answer"]
        assert "request to speak with staff" in first["answer"]
        assert "couldn't verify an answer" not in first["answer"]
        assert not followup["handoff"] and followup["ticket_id"] is None
        assert first["ticket_id"] in followup["answer"]
        tickets = client.get("/api/admin/tickets", headers=headers)
        tickets.raise_for_status()
        assert sum(str(t["conversation_id"]) == conversation_id for t in tickets.json()) == 1
        history = client.get("/api/conversations/" + conversation_id)
        history.raise_for_status()
        assert len(history.json()["messages"]) == 4
    report = {"passed": True, "tickets_created": 1, "followup_duplicates": 0, "results": results}
    identifier = get_repository().save_eval("human-request-regression", report)
    close_pool()
    print(json.dumps({"passed": True, "database_report_id": identifier}), flush=True)


if __name__ == "__main__":
    main()
