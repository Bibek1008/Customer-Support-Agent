"""Typed core objects shared across the system.

These are the nouns the rest of the code passes around: a ``Ticket``, the
``Message`` turns in a conversation, a retrieved ``Citation``, the ``Decision``
the agent reaches (answer or handoff), the per-step ``CostRecord``, and the
``Trace`` that ties a run together. Keeping them in one place means the agent,
the guardrails, the tools, and the eval harness all agree on shapes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """One turn in a conversation. ``content`` is already PII-redacted before
    it is stored or logged."""

    role: Role
    content: str
    created_at: datetime = Field(default_factory=_now)


class Citation(BaseModel):
    """A knowledge-base chunk (or tool result) the agent used to support a
    factual claim. Every claim in an answer must map to one of these."""

    source_id: str
    source_title: str
    url: str | None = None
    chunk: str
    score: float = Field(ge=0.0, le=1.0, description="Retrieval similarity, 0..1")


class TicketStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Ticket(BaseModel):
    """A support ticket. Created or updated through the ticketing tool, never
    by the model directly."""

    id: str = Field(default_factory=lambda: _id("tkt"))
    subject: str
    body: str
    customer_id: str | None = None
    status: TicketStatus = TicketStatus.OPEN
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class CostRecord(BaseModel):
    """Exact per-call cost, computed from real usage fields. This is arithmetic
    on ``usage`` values, not a benchmark estimate (FACTS.md Section 1)."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    usd: float = 0.0


class SpanRecord(BaseModel):
    """One step of a run: a model call, a tool call, or a guardrail check. Kept
    for the trace and, in aggregate, for the eval report."""

    name: str
    kind: Literal["model", "tool", "guardrail"]
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    cost: CostRecord | None = None


class DecisionType(str, Enum):
    ANSWER = "answer"
    HANDOFF = "handoff"


class Decision(BaseModel):
    """What the agent decided to do at the end of a run.

    ``confidence`` is the per-turn score; the run answers when it is at or above
    the handoff threshold tau* and escalates below it.
    """

    type: DecisionType
    answer: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    citations: list[Citation] = Field(default_factory=list)
    handoff_reason: str | None = None
    ticket_id: str | None = None


class Trace(BaseModel):
    """The full record of one conversation turn through the agent."""

    id: str = Field(default_factory=lambda: _id("trace"))
    conversation_id: str
    messages: list[Message] = Field(default_factory=list)
    spans: list[SpanRecord] = Field(default_factory=list)
    decision: Decision | None = None
    total_cost: CostRecord | None = None
    created_at: datetime = Field(default_factory=_now)

    def total_usd(self) -> float:
        """Sum the dollar cost across every model call in the run."""
        return round(
            sum(s.cost.usd for s in self.spans if s.cost is not None), 6
        )
