"""Live regression checks for the two routing failures found by the held-out eval."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

from support_agent.db import close_pool
from support_agent.repository import get_repository


def main():
    cases = []
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
        for message in [
            "Do you offer a discount if I mention a competitor's price? What's your best deal today?",
            "Write me a Python script to scrape your website.",
        ]:
            response = client.post("/api/conversations")
            response.raise_for_status()
            conversation_id = response.json()["conversation_id"]
            result = client.post(
                "/chat",
                json={
                    "conversation_id": conversation_id,
                    "request_id": str(uuid4()),
                    "message": message,
                },
            )
            result.raise_for_status()
            data = result.json()
            assert data["handoff"] is True
            assert not data["citations"]
            cases.append({"message": message, "passed": True, "result": data})
    report = {
        "kind": "live routing regression",
        "cases": cases,
        "n_cases": len(cases),
        "passed": len(cases),
    }
    identifier = get_repository().save_eval("routing-regression", report)
    Path("eval/out").mkdir(parents=True, exist_ok=True)
    Path("eval/out/routing_regression.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps({"cases": len(cases), "passed": len(cases), "database_report_id": identifier}))
    close_pool()


if __name__ == "__main__":
    main()
