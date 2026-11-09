"""Bounded PostgreSQL pool and additive, versioned application migrations."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from psycopg_pool import ConnectionPool

from support_agent.config import get_settings

SCHEMA_VERSION = 3


class DatabaseSchemaError(RuntimeError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS support_schema_versions (
    version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_sessions (
    token_hash TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS support_conversations (
    id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_token TEXT, lease_until TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS support_conversations_owner ON support_conversations(owner_hash);
CREATE TABLE IF NOT EXISTS support_turns (
    request_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES support_conversations(id),
    fingerprint TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('processing','completed','failed')),
    response JSONB, trace JSONB, error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS support_messages (
    id BIGSERIAL PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES support_conversations(id),
    request_id TEXT NOT NULL REFERENCES support_turns(request_id), role TEXT NOT NULL,
    content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(request_id, role)
);
CREATE INDEX IF NOT EXISTS support_messages_conversation ON support_messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS support_tickets (
    id TEXT PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL,
    customer_id TEXT, conversation_id TEXT REFERENCES support_conversations(id),
    request_id TEXT UNIQUE, status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS support_tickets_status ON support_tickets(status, created_at DESC);
CREATE TABLE IF NOT EXISTS support_ticket_replies (
    id BIGSERIAL PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES support_tickets(id),
    body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_audit (
    id BIGSERIAL PRIMARY KEY, event TEXT NOT NULL, principal_hash TEXT,
    data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_rate_limits (
    principal_hash TEXT NOT NULL, window_start BIGINT NOT NULL, count INTEGER NOT NULL,
    PRIMARY KEY(principal_hash, window_start)
);
CREATE TABLE IF NOT EXISTS support_eval_runs (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, report JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_demo_orders (
    id TEXT PRIMARY KEY, record JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@lru_cache(maxsize=1)
def get_pool() -> ConnectionPool:
    s = get_settings()
    pool = ConnectionPool(
        s.database_url,
        min_size=1,
        max_size=s.database_pool_size,
        open=False,
        timeout=10,
        max_waiting=30,
        check=ConnectionPool.check_connection,
        kwargs={"connect_timeout": 10},
    )
    try:
        pool.open(wait=True, timeout=15)
    except Exception:
        pool.close()
        raise
    return pool


@contextmanager
def connection():
    # SET LOCAL works with transaction poolers such as Neon/PgBouncer; startup
    # options and session-level SET are not reliable with pooled endpoints.
    with get_pool().connection() as conn:
        conn.execute("SET LOCAL statement_timeout = '15000ms'")
        conn.execute("SET LOCAL lock_timeout = '3000ms'")
        yield conn


def migrate() -> None:
    with get_pool().connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(391087421)")
        conn.execute(SCHEMA)
        conn.execute(
            "INSERT INTO support_schema_versions(version) VALUES (%s) ON CONFLICT DO NOTHING",
            (SCHEMA_VERSION,),
        )
    # Knowledge schema setup is an explicit migration operation in production.
    from support_agent.kb.store import VectorStore

    store = object.__new__(VectorStore)
    store.settings = get_settings()
    with get_pool().connection() as conn:
        store._conn = conn
        store._ensure_schema()
    if get_settings().business_mode == "demo":
        from psycopg.types.json import Jsonb

        from support_agent.tools.order_lookup import _FIXTURE_ORDERS

        with connection() as conn:
            for identifier, record in _FIXTURE_ORDERS.items():
                conn.execute(
                    "INSERT INTO support_demo_orders(id,record) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (identifier, Jsonb(record)),
                )


def check_database() -> None:
    with get_pool().connection() as conn:
        row = conn.execute("SELECT max(version) FROM support_schema_versions").fetchone()
        if row[0] is None or row[0] < SCHEMA_VERSION:
            raise DatabaseSchemaError(
                "Database schema is not current; run python -m support_agent.db"
            )


def close_pool() -> None:
    if get_pool.cache_info().currsize:
        get_pool().close()
        get_pool.cache_clear()


if __name__ == "__main__":
    try:
        migrate()
        print(f"Database migration {SCHEMA_VERSION} applied.")
    finally:
        close_pool()
