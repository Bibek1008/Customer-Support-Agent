"""Create, read, and update tickets against the ticketing system.

These are the tools that change state, so they are the ones that need gating in
production (a write tool should be behind confirmation, per the tool-surface
discipline). The client talks to a real ticketing API when
``TICKETING_BASE_URL`` is set in legacy development mode. With persistence enabled,
PostgreSQL is authoritative and the built-in staff inbox handles review and replies.
Only isolated non-persistent tests use the in-process store.

The tools return citable records (a ticket's fields) rather than free prose, so
the agent grounds any status claim it makes about a ticket.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from support_agent.config import get_settings
from support_agent.guardrails.pii import get_redactor
from support_agent.observability.tracing import sanitize
from support_agent.repository import NotFoundError, get_repository
from support_agent.request_context import current_request
from support_agent.schemas import Ticket, TicketStatus


class _TicketBackend:
    """Ticketing backend. Uses the HTTP API when configured, else in-memory."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._memory: dict[str, Ticket] = {}

    @property
    def _remote(self) -> bool:
        return bool(self.settings.ticketing_base_url)

    def _headers(self) -> dict[str, str]:
        key = self.settings.ticketing_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    def create(
        self,
        subject: str,
        body: str,
        customer_id: str | None,
        *,
        status: TicketStatus = TicketStatus.OPEN,
    ) -> Ticket:
        context = current_request.get()
        if self.settings.persistence_enabled and context is None:
            raise NotFoundError()
        clean = sanitize({"subject": subject, "body": body, "customer_id": customer_id})
        redactor = get_redactor()
        ticket = Ticket(
            status=status,
            subject=redactor.redact(clean["subject"]).text,
            body=redactor.redact(clean["body"]).text,
            customer_id=redactor.redact(clean["customer_id"]).text
            if clean["customer_id"]
            else None,
        )
        if self.settings.persistence_enabled:
            # LLM-supplied IDs are not authenticated customer identities.
            ticket.customer_id = None
            return get_repository().create_ticket(
                ticket,
                context.conversation_id,
                context.request_id,
            )
        if self._remote:
            resp = httpx.post(
                f"{self.settings.ticketing_base_url.rstrip('/')}/tickets",
                headers=self._headers(),
                json=ticket.model_dump(mode="json"),
                timeout=20.0,
            )
            resp.raise_for_status()
            return Ticket.model_validate(resp.json())
        self._memory[ticket.id] = ticket
        return ticket

    def get(self, ticket_id: str) -> Ticket | None:
        if self.settings.persistence_enabled:
            context = current_request.get()
            if context is None:
                raise NotFoundError()
            return get_repository().ticket(ticket_id, context.conversation_id)
        if self._remote:
            resp = httpx.get(
                f"{self.settings.ticketing_base_url.rstrip('/')}/tickets/{ticket_id}",
                headers=self._headers(),
                timeout=20.0,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return Ticket.model_validate(resp.json())
        return self._memory.get(ticket_id)

    def update_status(self, ticket_id: str, status: TicketStatus) -> Ticket | None:
        if self.settings.persistence_enabled:
            context = current_request.get()
            if context is None:
                raise NotFoundError()
            return get_repository().update_ticket(ticket_id, status, context.conversation_id)
        if self._remote:
            resp = httpx.patch(
                f"{self.settings.ticketing_base_url.rstrip('/')}/tickets/{ticket_id}",
                headers=self._headers(),
                json={"status": status.value},
                timeout=20.0,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return Ticket.model_validate(resp.json())
        ticket = self._memory.get(ticket_id)
        if ticket is None:
            return None
        ticket.status = status
        return ticket


_BACKEND: _TicketBackend | None = None


def _backend() -> _TicketBackend:
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _TicketBackend()
    return _BACKEND


@dataclass
class TicketResult:
    text: str
    ticket_id: str | None = None


def existing_ticket(
    conversation_id: str, reference: str | None = None, *, request_only: bool = False
) -> Ticket | None:
    """Only reuse authoritative tickets belonging to the authenticated conversation."""
    if get_settings().persistence_enabled:
        context = current_request.get()
        if context is None or context.conversation_id != conversation_id:
            return None
        return get_repository().existing_ticket(
            context.conversation_id, context.request_id if request_only else None
        )
    if request_only or reference is None:
        return None
    ticket = _backend().get(reference)
    return ticket if ticket and ticket.status != TicketStatus.RESOLVED else None


def create_ticket(subject: str, body: str, customer_id: str | None = None) -> TicketResult:
    ticket = _backend().create(subject=subject, body=body, customer_id=customer_id)
    return TicketResult(
        text=f"Created ticket {ticket.id} ({ticket.status.value}): {ticket.subject}.",
        ticket_id=ticket.id,
    )


def read_ticket(ticket_id: str) -> TicketResult:
    ticket = _backend().get(ticket_id)
    if ticket is None:
        return TicketResult(text=f"No ticket found with id {ticket_id}.")
    return TicketResult(
        text=(f"Ticket {ticket.id}: status {ticket.status.value}, subject '{ticket.subject}'."),
        ticket_id=ticket.id,
    )


def update_ticket_status(ticket_id: str, status: str) -> TicketResult:
    try:
        new_status = TicketStatus(status)
    except ValueError:
        allowed = ", ".join(s.value for s in TicketStatus)
        return TicketResult(text=f"Invalid status {status!r}. Use one of: {allowed}.")
    ticket = _backend().update_status(ticket_id, new_status)
    if ticket is None:
        return TicketResult(text=f"No ticket found with id {ticket_id}.")
    return TicketResult(
        text=f"Ticket {ticket.id} is now {ticket.status.value}.", ticket_id=ticket.id
    )
