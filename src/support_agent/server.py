"""FastAPI service: POST /chat, GET /healthz.

The gateway is thin: it validates the request, runs one agent turn, and returns
the decision plus the citations and the run's cost. All the policy lives in the
agent loop and the guardrails; the service just exposes them over HTTP.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from support_agent import __version__
from support_agent.agent.groq_client import GroqRequestError
from support_agent.agent.loop import run_turn
from support_agent.agent.models import classifier_kwargs, reasoner_kwargs
from support_agent.config import get_settings
from support_agent.observability.tracing import get_langfuse, shutdown_tracing
from support_agent.schemas import Citation, DecisionType, Message


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from support_agent.db import close_pool
    from support_agent.http_api import check_production_dependencies, startup

    started = time.perf_counter()
    settings = get_settings()
    startup(defer_dependencies=settings.app_env == "production")
    readiness_task = None
    if settings.app_env == "production":
        readiness_task = asyncio.create_task(asyncio.to_thread(check_production_dependencies))
    else:
        get_langfuse()
    logging.getLogger(__name__).info(
        "startup operation=lifespan_setup elapsed_ms=%.1f status=ok",
        (time.perf_counter() - started) * 1000,
    )
    try:
        yield
    finally:
        if readiness_task is not None:
            try:
                await readiness_task
            except Exception as error:  # noqa: BLE001 - background readiness must not break shutdown
                logging.getLogger(__name__).warning(
                    "startup readiness unavailable failure=%s", type(error).__name__
                )
        shutdown_tracing()
        close_pool()


app = FastAPI(
    title="support-agent",
    version=__version__,
    lifespan=lifespan,
    docs_url=None if get_settings().app_env == "production" else "/docs",
    redoc_url=None if get_settings().app_env == "production" else "/redoc",
    openapi_url=None if get_settings().app_env == "production" else "/openapi.json",
)


@app.exception_handler(GroqRequestError)
async def provider_error_handler(request, error: GroqRequestError) -> JSONResponse:
    if error.status_code == 429:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "60"},
            content={
                "detail": "The assistant has reached its usage limit. Please try again later."
            },
        )
    return JSONResponse(
        status_code=502,
        content={"detail": "The assistant could not complete its response. Please try again."},
    )


@app.exception_handler(httpx.RequestError)
async def connection_error_handler(request, error: httpx.RequestError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "The assistant cannot reach its services right now. Please try again."},
    )


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    from support_agent.http_api import browser_page

    return browser_page("chat.html")


class ChatRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    message: str = Field(..., min_length=1, max_length=4000)
    customer_id: str | None = None
    request_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")


class ChatResponse(BaseModel):
    conversation_id: str
    request_id: str | None = None
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
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """Run one customer turn through the agent."""
    if get_settings().persistence_enabled:
        from support_agent.http_api import durable_chat

        return ChatResponse.model_validate(durable_chat(req, request, run_turn))
    if get_settings().app_env != "test":
        raise HTTPException(503, "Persistent storage is required to serve chat.")
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


from support_agent.http_api import install

install(app)
