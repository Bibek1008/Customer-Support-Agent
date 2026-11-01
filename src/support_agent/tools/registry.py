"""Tool JSON schemas and dispatch.

The schemas are what the model sees. They use strict tool use
(``strict: true`` + ``additionalProperties: false``) so a tool call's ``input``
validates exactly and can be parsed with ``json.loads`` rather than string-
matched. Read-only tools are marked parallel-safe; the two write tools
(``create_ticket``, ``update_ticket_status``) and the escalation tool are not,
because they change state and should be gated in production.

``dispatch`` runs one tool call and returns a :class:`ToolOutcome`. The knowledge
base tool carries citations back so the loop can attach them to the answer.
Escalation does not execute here; it returns a handoff signal the loop packages
with the transcript and confidence, which are not the model's to supply.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from support_agent.schemas import Citation
from support_agent.tools import knowledge_base, order_lookup, ticketing


@dataclass
class ToolOutcome:
    text: str
    citations: list[Citation] = field(default_factory=list)
    is_handoff: bool = False
    handoff_reason: str | None = None
    ticket_id: str | None = None


# The tool definitions passed to the Anthropic Messages API.
TOOL_SCHEMAS: list[dict] = [
    {
        "name": "knowledge_base",
        "description": (
            "Search the product, policy, billing, and account knowledge base. "
            "Returns the most relevant chunks with their sources. Cite only "
            "chunks this tool returns."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up"},
                "k": {
                    "type": "integer",
                    "description": "How many chunks to return (default 4)",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "order_lookup",
        "description": "Look up the status of an order by its order ID (e.g. ORD-1001).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order ID"},
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_ticket",
        "description": "Read a support ticket by its ID.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "The ticket ID"},
            },
            "required": ["ticket_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_ticket",
        "description": (
            "Create a support ticket. Use when the issue needs a record or "
            "a follow-up. A state-changing tool."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "customer_id": {"type": "string"},
            },
            "required": ["subject", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_ticket_status",
        "description": (
            "Update a ticket's status to one of: open, resolved, escalated. "
            "A state-changing tool."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["open", "resolved", "escalated"],
                },
            },
            "required": ["ticket_id", "status"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate to a human agent. Use when you cannot answer confidently, "
            "the request is out of scope, or the policy says to hand off. Give a "
            "short reason."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why you are escalating"},
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]

# Read-only tools may run in parallel; the loop serializes the rest.
PARALLEL_SAFE = frozenset({"knowledge_base", "order_lookup", "read_ticket"})


def dispatch(name: str, tool_input: dict) -> ToolOutcome:
    """Run one tool call and return its outcome.

    ``tool_input`` is already a parsed dict (from ``tool_use.input``), never a
    raw string. Escalation is not executed here; it signals the loop.
    """
    if name == "knowledge_base":
        result = knowledge_base.search_knowledge_base(
            query=tool_input["query"], k=int(tool_input.get("k", 4))
        )
        return ToolOutcome(text=result.text, citations=result.citations)

    if name == "order_lookup":
        result = order_lookup.lookup_order(tool_input["order_id"])
        return ToolOutcome(text=result.text)

    if name == "read_ticket":
        result = ticketing.read_ticket(tool_input["ticket_id"])
        return ToolOutcome(text=result.text, ticket_id=result.ticket_id)

    if name == "create_ticket":
        result = ticketing.create_ticket(
            subject=tool_input["subject"],
            body=tool_input["body"],
            customer_id=tool_input.get("customer_id"),
        )
        return ToolOutcome(text=result.text, ticket_id=result.ticket_id)

    if name == "update_ticket_status":
        result = ticketing.update_ticket_status(
            ticket_id=tool_input["ticket_id"], status=tool_input["status"]
        )
        return ToolOutcome(text=result.text, ticket_id=result.ticket_id)

    if name == "escalate_to_human":
        # Signal the loop, which owns the transcript and confidence.
        return ToolOutcome(
            text="",
            is_handoff=True,
            handoff_reason=tool_input["reason"],
        )

    return ToolOutcome(text=f"Unknown tool {name!r}.")
