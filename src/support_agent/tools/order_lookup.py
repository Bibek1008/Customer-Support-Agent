"""Example domain tool: order and account status by ID.

This is the kind of read-only tool a support agent needs: given an order ID, look
up its status. In production it calls the order service; here it reads a small
in-repo fixture so the loop and the eval suite run end to end without a live
backend. The important property is the shape: it returns a factual record the
agent can cite, and it is a tool the harness can call during testing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from support_agent.config import get_settings

# In-repo fixtures so the demo and the eval suite resolve real order IDs. A
# deployment sets TICKETING_BASE_URL / an order service URL and this falls back
# to the live call.
_FIXTURE_ORDERS: dict[str, dict[str, str]] = {
    "ORD-1001": {
        "status": "shipped",
        "carrier": "UPS",
        "tracking": "1Z-REDACTED",
        "eta": "2026-07-28",
        "items": "1x Standing Desk",
    },
    "ORD-1002": {
        "status": "processing",
        "carrier": "",
        "tracking": "",
        "eta": "2026-07-30",
        "items": "2x Desk Lamp",
    },
    "ORD-1003": {
        "status": "delivered",
        "carrier": "FedEx",
        "tracking": "77-REDACTED",
        "eta": "2026-07-20",
        "items": "1x Office Chair",
    },
}


@dataclass
class OrderResult:
    text: str
    found: bool


def lookup_order(order_id: str) -> OrderResult:
    """Return the status of ``order_id`` as a citable record."""
    order_id = order_id.strip().upper()
    settings = get_settings()

    base = settings.ticketing_base_url or os.environ.get("ORDER_SERVICE_URL", "")
    if base:
        try:
            resp = httpx.get(
                f"{base.rstrip('/')}/orders/{order_id}",
                headers=_auth_headers(settings.ticketing_api_key),
                timeout=15.0,
            )
            if resp.status_code == 404:
                return OrderResult(text=f"No order found with id {order_id}.", found=False)
            resp.raise_for_status()
            record = resp.json()
            return OrderResult(text=_format(order_id, record), found=True)
        except Exception as exc:  # surface the failure; the agent can escalate
            return OrderResult(
                text=f"The order service could not be reached for {order_id}: {exc}",
                found=False,
            )

    record = _FIXTURE_ORDERS.get(order_id)
    if record is None:
        return OrderResult(text=f"No order found with id {order_id}.", found=False)
    return OrderResult(text=_format(order_id, record), found=True)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _format(order_id: str, record: dict[str, str]) -> str:
    parts = [f"Order {order_id}: status {record.get('status', 'unknown')}"]
    if record.get("items"):
        parts.append(f"items {record['items']}")
    if record.get("carrier"):
        parts.append(f"carrier {record['carrier']}")
    if record.get("eta"):
        parts.append(f"estimated delivery {record['eta']}")
    return ", ".join(parts) + "."
