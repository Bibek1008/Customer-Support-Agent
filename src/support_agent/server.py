"""FastAPI service: POST /chat, GET /healthz.

The gateway is thin: it validates the request, runs one agent turn, and returns
the decision plus the citations and the run's cost. All the policy lives in the
agent loop and the guardrails; the service just exposes them over HTTP.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from support_agent import __version__
from support_agent.agent.loop import run_turn
from support_agent.agent.models import classifier_kwargs, reasoner_kwargs
from support_agent.config import get_settings
from support_agent.observability.tracing import get_langfuse, shutdown_tracing
from support_agent.schemas import Citation, DecisionType, Message


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_langfuse()
    try:
        yield
    finally:
        shutdown_tracing()


app = FastAPI(title="support-agent", version=__version__, lifespan=lifespan)


class ChatRequest(BaseModel):
    conversation_id: str = Field(..., description="Stable ID for this conversation")
    message: str = Field(..., description="The customer's message")
    customer_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    langfuse_trace_id: str | None = None
    decision: DecisionType
    answer: str
    confidence: float
    threshold: float
    handoff: bool
    ticket_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    cost_usd: float = 0.0


@app.get("/healthz")
def healthz() -> dict:
    """Liveness check plus the model IDs the service is configured to use."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "llm_provider": settings.llm_provider,
        "agent_model": reasoner_kwargs()["model"],
        "classifier_model": classifier_kwargs()["model"],
        "handoff_threshold": settings.handoff_threshold,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Run one customer turn through the agent."""
    trace = run_turn(
        conversation_id=req.conversation_id,
        user_message=req.message,
        customer_id=req.customer_id,
    )
    decision = trace.decision
    assert decision is not None  # run_turn always sets a decision
    return ChatResponse(
        conversation_id=req.conversation_id,
        langfuse_trace_id=trace.langfuse_trace_id,
        decision=decision.type,
        answer=decision.answer or "",
        confidence=decision.confidence,
        threshold=decision.threshold,
        handoff=decision.type == DecisionType.HANDOFF,
        ticket_id=decision.ticket_id,
        citations=decision.citations,
        cost_usd=trace.total_usd(),
    )


def _last_assistant(messages: list[Message]) -> str:
    for msg in reversed(messages):
        if msg.role.value == "assistant":
            return msg.content
    return ""
