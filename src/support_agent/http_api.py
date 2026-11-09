"""Browser sessions, durable request lifecycle, and separately protected staff APIs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from support_agent.config import get_settings
from support_agent.db import DatabaseSchemaError, check_database, get_pool
from support_agent.guardrails.pii import get_redactor
from support_agent.observability.audit import capture_events
from support_agent.repository import (
    ConflictError,
    NotFoundError,
    RateLimitError,
    get_repository,
    token_hash,
)
from support_agent.request_context import (
    RequestContext,
    TurnTimeoutError,
    current_request,
    remaining_timeout,
)
from support_agent.schemas import DecisionType, Message, TicketStatus

LOGGER = logging.getLogger(__name__)
WEB = Path(__file__).resolve().parents[2] / "website"
COOKIE = "support_session"
_STAFF_AUTH_FAILURES: dict[str, tuple[int, int]] = {}
_STAFF_AUTH_FAILURES_LOCK = threading.Lock()
_STAFF_AUTH_FAILURE_LIMIT = 10
router = APIRouter()


def startup():
    settings = get_settings()
    settings.validate_production()
    if settings.app_env == "production":
        from support_agent.agent.models import validate_credentials

        validate_credentials()
    if settings.persistence_enabled:
        check_database()
    if settings.app_env == "production":
        from support_agent.kb.store import get_store

        if not get_redactor()._presidio:
            raise RuntimeError("Production requires a functioning Presidio installation.")
        if not get_store()._use_db or any(
            not get_store().count(profile=p)
            for p in ("brazil_consumer_law", "olist_transaction_profile", "olist_demo_policy")
        ):
            raise RuntimeError("Production requires an ingested PostgreSQL knowledge base.")


def browser_page(name):
    path = WEB / name
    scripts = re.findall(
        r"<script>(.*?)</script>", path.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"
        for script in scripts
    )
    return FileResponse(
        path,
        headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self' "
            + hashes
            + "; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        },
    )


class BodyLimitMiddleware:
    """Bound actual bytes, including chunked bodies, before JSON parsing."""

    def __init__(self, app, limit=16384):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PATCH", "PUT"}:
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse(
                    status_code=413, content={"detail": "Request is too large."}
                )(scope, receive, send)
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def require_persistence():
    if not get_settings().persistence_enabled:
        raise HTTPException(503, "Persistent storage is not configured.")


def require_owner(request: Request) -> str:
    require_persistence()
    key = get_settings().service_api_key
    if key and hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + key):
        return "service:" + token_hash(key)
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 100 or not get_repository().session_exists(token_hash(token)):
        raise HTTPException(401, "Your support session expired. Refresh this page.")
    return token_hash(token)


def require_admin(request: Request):
    key = get_settings().admin_api_key
    if not key or not hmac.compare_digest(
        request.headers.get("authorization", ""), "Bearer " + key
    ):
        host = request.client.host if request.client else "unknown"
        principal = token_hash(host)
        window = int(time.time()) // 60
        with _STAFF_AUTH_FAILURES_LOCK:
            if len(_STAFF_AUTH_FAILURES) > 10_000:
                _STAFF_AUTH_FAILURES.clear()
            previous = _STAFF_AUTH_FAILURES.get(principal)
            count = previous[1] + 1 if previous and previous[0] == window else 1
            _STAFF_AUTH_FAILURES[principal] = (window, count)
        if count > _STAFF_AUTH_FAILURE_LIMIT:
            raise HTTPException(
                429,
                "Too many unsuccessful staff authentication attempts. Try again next minute.",
                headers={"Retry-After": "60"},
            )
        raise HTTPException(
            401, "Staff authentication required.", headers={"WWW-Authenticate": "Bearer"}
        )
    host = request.client.host if request.client else "unknown"
    with _STAFF_AUTH_FAILURES_LOCK:
        _STAFF_AUTH_FAILURES.pop(token_hash(host), None)
    require_persistence()
    get_repository().check_rate("staff:" + token_hash(key), limit=120)


def check_ingress_rate(request):
    # Forwarding headers are not trusted for this limit. Also enforce IP limits at the proxy.
    host = request.client.host if request.client else "unknown"
    get_repository().check_rate("ip:" + token_hash(host), limit=120)


@router.post("/api/session")
def session(request: Request, response: Response):
    require_persistence()
    check_ingress_rate(request)
    token, repo = request.cookies.get(COOKIE), get_repository()
    if not token or len(token) > 100 or not repo.session_exists(token_hash(token)):
        token = secrets.token_urlsafe(32)
        repo.create_session(token)
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=get_settings().app_env == "production",
            samesite="strict",
            max_age=get_settings().session_days * 86400,
            path="/",
        )
    settings = get_settings()
    return {
        "conversations": jsonable_encoder(repo.conversations(token_hash(token))),
        "business_name": settings.business_name,
        "business_mode": settings.business_mode,
    }


@router.delete("/api/session", status_code=204)
def end_session(request: Request, response: Response):
    require_persistence()
    check_ingress_rate(request)
    token = request.cookies.get(COOKIE)
    if token and len(token) <= 100:
        get_repository().delete_session(token)
    response.delete_cookie(
        COOKIE,
        path="/",
        httponly=True,
        secure=get_settings().app_env == "production",
        samesite="strict",
    )


@router.post("/api/conversations")
def new_conversation(
    profile: Literal["olist_demo", "office_store"] = "olist_demo",
    owner: str = Depends(require_owner),
):
    get_repository().check_rate(owner)
    return {"conversation_id": get_repository().create_conversation(owner, profile=profile)}


@router.get("/api/olist/accounts")
def olist_accounts(owner: str = Depends(require_owner)):
    from support_agent.olist.queries import dataset_status

    return {
        **dataset_status(),
        "disclosure": "Public anonymized historical profiles, not authenticated customer accounts or live customer data.",
    }


class DemoAccountSelection(BaseModel):
    account_alias: str = Field(pattern=r"^demo-customer-[0-9]{2}$")


@router.put("/api/conversations/{conversation_id}/demo-account")
def select_olist_account(
    conversation_id: UUID, body: DemoAccountSelection, owner: str = Depends(require_owner)
):
    from support_agent.olist.queries import bind_account

    if not bind_account(str(conversation_id), owner, body.account_alias):
        raise HTTPException(409, "Start a new chat and choose a valid historical profile.")
    from support_agent.olist.queries import account_orders

    return {
        "profile": "olist_demo",
        "account": body.account_alias,
        "orders": account_orders(str(conversation_id), owner),
        "disclosure": "Olist Brazilian E-Commerce Public Dataset, historical records; no live tracking or order actions.",
    }


@router.get("/api/conversations/{conversation_id}/demo-account")
def current_demo_account(conversation_id: UUID, owner: str = Depends(require_owner)):
    from support_agent.olist.queries import current_selection

    return current_selection(str(conversation_id), owner)


@router.delete("/api/conversations/{conversation_id}/demo-account")
def reset_olist_profile(conversation_id: UUID, owner: str = Depends(require_owner)):
    from support_agent.olist.queries import reset_profile

    if not reset_profile(str(conversation_id), owner):
        raise NotFoundError()
    return {"profile": "office_store"}


@router.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: UUID, owner: str = Depends(require_owner)):
    return {
        "conversation_id": str(conversation_id),
        "messages": jsonable_encoder(
            get_repository().history(str(conversation_id), owner, limit=500)
        ),
    }


@router.get("/readyz")
def readyz():
    require_persistence()
    check_database()
    return {"status": "ready", "persistence": "postgresql"}


def durable_chat(req, request, run_turn):
    if not req.message.strip():
        raise HTTPException(422, "Message cannot be blank.")
    owner = require_owner(request)
    check_ingress_rate(request)
    repo = get_repository()
    repo.check_rate(owner)
    if req.customer_id:
        raise HTTPException(422, "Customer identity requires a verified account integration.")
    try:
        request_id = str(UUID(req.request_id)) if req.request_id else str(uuid4())
    except ValueError as error:
        raise HTTPException(422, "Request ID must be a UUID.") from error
    lease_token = str(uuid4())
    fingerprint = hashlib.sha256((req.conversation_id + "\0" + req.message).encode()).hexdigest()
    profile, account_alias = repo.conversation_profile(req.conversation_id, owner)
    cached = repo.begin_turn(
        req.conversation_id,
        owner,
        request_id,
        get_redactor().redact(req.message).text,
        fingerprint,
        lease_token,
    )
    if cached is not None:
        return cached
    context = current_request.set(
        RequestContext(
            req.conversation_id,
            request_id,
            owner,
            time.monotonic() + 180,
            kb_profile=profile,
            olist_account=account_alias,
        )
    )
    try:
        history = [
            Message(role="assistant" if m["role"] == "staff" else m["role"], content=m["content"])
            for m in repo.history(req.conversation_id, owner)
        ]
        with capture_events() as events:
            trace = run_turn(
                conversation_id=req.conversation_id,
                user_message=req.message,
                customer_id=None,
                history=history,
            )
        remaining_timeout()
        d = trace.decision
        if d is None:
            raise RuntimeError("Agent did not produce a decision")
        result = {
            "conversation_id": req.conversation_id,
            "request_id": request_id,
            "langfuse_trace_id": trace.langfuse_trace_id,
            "decision": d.type.value,
            "answer": get_redactor().redact(d.answer or "").text,
            "confidence": d.confidence,
            "threshold": d.threshold,
            "handoff": d.type == DecisionType.HANDOFF,
            "ticket_id": d.ticket_id,
            "citations": [c.model_dump(mode="json") for c in d.citations],
            "cost_usd": round(
                trace.total_usd() + sum(e.get("guardrail.safety.cost_usd", 0) for e in events), 6
            ),
        }
        repo.complete_turn(
            req.conversation_id,
            request_id,
            result,
            {**trace.model_dump(mode="json"), "guardrails": events},
            lease_token,
        )
        return result
    except Exception as error:
        try:
            repo.fail_turn(req.conversation_id, request_id, type(error).__name__, lease_token)
        except (psycopg.Error, PoolTimeout):
            LOGGER.error("Could not record failed turn")
        raise
    finally:
        current_request.reset(context)


@router.get("/admin/inbox", include_in_schema=False)
def staff_frontend():
    return browser_page("staff.html")


@router.get("/api/admin/tickets", dependencies=[Depends(require_admin)])
def list_tickets():
    return jsonable_encoder(get_repository().tickets())


class StaffReply(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.post("/api/admin/tickets/{ticket_id}/replies", dependencies=[Depends(require_admin)])
def reply(ticket_id: str, body: StaffReply):
    if not body.message.strip():
        raise HTTPException(422, "Reply cannot be blank.")
    get_repository().reply(ticket_id, get_redactor().redact(body.message).text)
    return {"saved": True}


class StaffStatus(BaseModel):
    status: TicketStatus


@router.patch("/api/admin/tickets/{ticket_id}", dependencies=[Depends(require_admin)])
def update_status(ticket_id: str, body: StaffStatus):
    ticket = get_repository().update_ticket(ticket_id, body.status)
    if not ticket:
        raise NotFoundError()
    get_repository().audit("staff_status", {"ticket_id": ticket_id, "status": body.status.value})
    return jsonable_encoder(ticket)


@router.get("/api/admin/evaluations", dependencies=[Depends(require_admin)])
def evaluations():
    return jsonable_encoder(get_repository().evaluations())


@router.get("/api/admin/activity", dependencies=[Depends(require_admin)])
def activity():
    return jsonable_encoder(get_repository().recent_turns())


@router.get("/api/admin/tracing-budget", dependencies=[Depends(require_admin)])
def tracing_budget():
    from datetime import UTC, datetime

    month = datetime.now(UTC).strftime("%Y-%m")
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT trace_count FROM support_trace_budget WHERE month=%s", (month,)
        ).fetchone()
    return {
        "month": month,
        "sampled_trace_count": row[0] if row else 0,
        "application_trace_cap": get_settings().langfuse_monthly_trace_budget,
        "sample_rate": get_settings().langfuse_sample_rate,
        "note": "Application-side trace cap; monitor actual Langfuse monthly units in its dashboard.",
    }


def install(app):
    from support_agent.guardrails.safety import SafetyUnavailableError

    settings = get_settings()
    app.include_router(router)
    app.add_middleware(BodyLimitMiddleware)
    if settings.app_env == "production":
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=[urlparse(settings.app_origin).hostname]
        )

    @app.middleware("http")
    async def security_headers(request, call_next):
        started = time.perf_counter()
        origin = request.headers.get("origin")
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            if origin and origin.rstrip("/") != get_settings().app_origin.rstrip("/"):
                return JSONResponse(status_code=403, content={"detail": "Origin is not allowed."})
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    status_code=403, content={"detail": "Cross-site request is not allowed."}
                )
        try:
            response = await call_next(request)
        except Exception as error:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            LOGGER.error(
                "request failed method=%s route=%s error=%s duration_ms=%.1f",
                request.method,
                route,
                type(error).__name__,
                (time.perf_counter() - started) * 1000,
            )
            raise
        route = getattr(request.scope.get("route"), "path", "unmatched")
        request_id = str(uuid4())
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            "request completed id=%s method=%s route=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            route,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "X-Frame-Options": "DENY",
                "Cache-Control": "no-store",
            }
        )
        if get_settings().app_env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(psycopg.Error)
    @app.exception_handler(PoolTimeout)
    @app.exception_handler(DatabaseSchemaError)
    async def database_error(request, error):
        LOGGER.error("Database request failed (%s)", type(error).__name__)
        return JSONResponse(
            status_code=503,
            content={"detail": "Storage is unavailable. Please retry the same request."},
        )

    @app.exception_handler(NotFoundError)
    async def not_found(request, error):
        return JSONResponse(status_code=404, content={"detail": "Record not found."})

    @app.exception_handler(ConflictError)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RateLimitError)
    async def rate_limit(request, error):
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "60"},
            content={"detail": "Too many requests. Please wait a minute and try again."},
        )

    @app.exception_handler(TurnTimeoutError)
    async def turn_timeout(request, error):
        return JSONResponse(
            status_code=504,
            content={"detail": "This request took too long. Please retry the same request."},
        )

    @app.exception_handler(SafetyUnavailableError)
    async def safety_unavailable(request, error):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "The safety check is temporarily unavailable. Please try again shortly."
            },
        )
