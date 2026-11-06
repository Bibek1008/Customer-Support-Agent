"""The escalate_to_human tool.

When the agent should not answer itself, it escalates: this packages the
conversation transcript, the confidence score, and the reason into a ticket for
the human queue and returns a message for the customer. Escalation is a
first-class outcome, not a failure. It is how the agent avoids answering when it
cannot support the answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from support_agent.schemas import Message, TicketStatus
from support_agent.tools.ticketing import _backend


@dataclass
class HandoffResult:
    text: str  # message for the customer
    ticket_id: str


def escalate_to_human(
    reason: str,
    transcript: list[Message],
    confidence: float,
    customer_id: str | None = None,
) -> HandoffResult:
    """Open an escalated ticket carrying the transcript and confidence."""
    body_lines = [f"Escalation reason: {reason}", f"Confidence at handoff: {confidence:.2f}", ""]
    body_lines.append("Transcript:")
    for msg in transcript:
        body_lines.append(f"  {msg.role.value}: {msg.content}")
    body = "\n".join(body_lines)

    ticket = _backend().create(
        subject="Escalated to human agent",
        body=body,
        customer_id=customer_id,
    )
    _backend().update_status(ticket.id, TicketStatus.ESCALATED)

    message = (
        "I couldn't verify an answer, so I've saved your request for support review. "
        f"Your reference is {ticket.id}. You can check this chat for a staff reply."
    )
    return HandoffResult(text=message, ticket_id=ticket.id)
