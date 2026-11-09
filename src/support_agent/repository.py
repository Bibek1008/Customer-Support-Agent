"""Durable support records. Database errors propagate; there is no memory fallback."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from support_agent.config import get_settings
from support_agent.db import connection
from support_agent.observability.tracing import sanitize
from support_agent.schemas import Ticket, TicketStatus


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class RateLimitError(Exception):
    pass


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Repository:
    def demo_order(self, order_id: str) -> dict | None:
        with connection() as conn:
            row = conn.execute(
                "SELECT record FROM support_demo_orders WHERE id=%s", (order_id,)
            ).fetchone()
            return row[0] if row else None

    def create_session(self, token: str) -> None:
        expires = datetime.now(UTC) + timedelta(days=get_settings().session_days)
        with connection() as conn:
            conn.execute(
                "INSERT INTO support_sessions(token_hash, expires_at) VALUES (%s,%s)",
                (token_hash(token), expires),
            )

    def session_exists(self, owner: str) -> bool:
        with connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM support_sessions WHERE token_hash=%s AND expires_at>now()",
                    (owner,),
                ).fetchone()
                is not None
            )

    def check_rate(self, principal: str, limit: int | None = None) -> None:
        window = int(time.time()) // 60
        with connection() as conn:
            count = conn.execute(
                """
                INSERT INTO support_rate_limits(principal_hash,window_start,count) VALUES (%s,%s,1)
                ON CONFLICT(principal_hash,window_start) DO UPDATE SET count=support_rate_limits.count+1
                RETURNING count
            """,
                (principal, window),
            ).fetchone()[0]
        if count > (limit or get_settings().rate_limit_per_minute):
            raise RateLimitError()

    def create_conversation(self, owner: str) -> str:
        identifier = str(uuid4())
        with connection() as conn:
            conn.execute(
                "INSERT INTO support_conversations(id,owner_hash) VALUES (%s,%s)",
                (identifier, owner),
            )
        return identifier

    def conversations(self, owner: str) -> list[dict]:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id,created_at,updated_at FROM support_conversations WHERE owner_hash=%s ORDER BY updated_at DESC LIMIT 50",
                (owner,),
            )
            return cur.fetchall()

    def require_owner(self, conversation_id: str, owner: str) -> None:
        with connection() as conn:
            if not conn.execute(
                "SELECT 1 FROM support_conversations WHERE id=%s AND owner_hash=%s",
                (conversation_id, owner),
            ).fetchone():
                raise NotFoundError()

    def history(self, conversation_id: str, owner: str, limit: int | None = None) -> list[dict]:
        self.require_owner(conversation_id, owner)
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT role,content,created_at,result FROM (
                    SELECT m.role,m.content,m.created_at,
                           CASE WHEN m.role='assistant' THEN t.response ELSE NULL END AS result FROM support_messages m
                    JOIN support_turns t ON t.request_id=m.request_id
                    WHERE m.conversation_id=%s AND t.state='completed'
                    UNION ALL
                    SELECT 'staff',r.body,r.created_at,NULL AS result FROM support_ticket_replies r
                    JOIN support_tickets t ON t.id=r.ticket_id WHERE t.conversation_id=%s
                ) messages ORDER BY created_at DESC LIMIT %s
            """,
                (conversation_id, conversation_id, limit or get_settings().history_messages),
            )
            return list(reversed(cur.fetchall()))

    def begin_turn(
        self,
        conversation_id: str,
        owner: str,
        request_id: str,
        message: str,
        fingerprint: str,
        lease_token: str,
    ) -> dict | None:
        """Acquire a short database lease; no transaction stays open during inference."""
        with connection() as conn:
            row = conn.execute(
                "SELECT owner_hash FROM support_conversations WHERE id=%s FOR UPDATE",
                (conversation_id,),
            ).fetchone()
            if not row or row[0] != owner:
                raise NotFoundError()
            prior = conn.execute(
                "SELECT conversation_id,fingerprint,state,response FROM support_turns WHERE request_id=%s",
                (request_id,),
            ).fetchone()
            if prior:
                if prior[0] != conversation_id or prior[1] != fingerprint:
                    raise ConflictError("Request ID was already used for another message.")
                if prior[2] == "completed":
                    return prior[3]
            lease = conn.execute(
                """
                UPDATE support_conversations SET lease_token=%s,lease_until=now()+interval '5 minutes'
                WHERE id=%s AND (lease_until IS NULL OR lease_until<now()) RETURNING id
            """,
                (lease_token, conversation_id),
            ).fetchone()
            if not lease:
                raise ConflictError("A message is already being processed. Please wait.")
            conn.execute(
                """
                INSERT INTO support_turns(request_id,conversation_id,fingerprint,state) VALUES (%s,%s,%s,'processing')
                ON CONFLICT(request_id) DO UPDATE SET state='processing',error_code=NULL
            """,
                (request_id, conversation_id, fingerprint),
            )
            conn.execute(
                """
                INSERT INTO support_messages(conversation_id,request_id,role,content) VALUES (%s,%s,'user',%s)
                ON CONFLICT(request_id,role) DO NOTHING
            """,
                (conversation_id, request_id, message),
            )
        return None

    def complete_turn(
        self, conversation_id: str, request_id: str, response: dict, trace: dict, lease_token: str
    ) -> None:
        response, trace = sanitize(response), sanitize(trace)
        with connection() as conn:
            lease = conn.execute(
                "SELECT 1 FROM support_conversations WHERE id=%s AND lease_token=%s FOR UPDATE",
                (conversation_id, lease_token),
            ).fetchone()
            if not lease:
                raise ConflictError("Request lease expired. Please retry.")
            conn.execute(
                """
                INSERT INTO support_messages(conversation_id,request_id,role,content) VALUES (%s,%s,'assistant',%s)
                ON CONFLICT(request_id,role) DO NOTHING
            """,
                (conversation_id, request_id, response["answer"]),
            )
            conn.execute(
                "UPDATE support_turns SET state='completed',response=%s,trace=%s,completed_at=now() WHERE request_id=%s",
                (Jsonb(response), Jsonb(trace), request_id),
            )
            conn.execute(
                "UPDATE support_conversations SET lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s AND lease_token=%s",
                (conversation_id, lease_token),
            )

    def fail_turn(
        self, conversation_id: str, request_id: str, error_code: str, lease_token: str
    ) -> None:
        with connection() as conn:
            if not conn.execute(
                "SELECT 1 FROM support_conversations WHERE id=%s AND lease_token=%s FOR UPDATE",
                (conversation_id, lease_token),
            ).fetchone():
                return
            conn.execute(
                "UPDATE support_turns SET state='failed',error_code=%s,completed_at=now() WHERE request_id=%s AND state='processing'",
                (error_code, request_id),
            )
            conn.execute(
                "UPDATE support_conversations SET lease_token=NULL,lease_until=NULL WHERE id=%s AND lease_token=%s",
                (conversation_id, lease_token),
            )

    def create_ticket(
        self, ticket: Ticket, conversation_id: str | None, request_id: str | None
    ) -> Ticket:
        clean = sanitize(ticket.model_dump(mode="json"))
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO support_tickets(id,subject,body,customer_id,status,conversation_id,request_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(request_id) DO UPDATE SET updated_at=now()
                RETURNING id,subject,body,customer_id,status,created_at,updated_at
            """,
                (
                    ticket.id,
                    clean["subject"],
                    clean["body"],
                    clean["customer_id"],
                    ticket.status.value,
                    conversation_id,
                    request_id,
                ),
            )
            return Ticket.model_validate(cur.fetchone())

    def ticket(self, ticket_id: str, conversation_id: str | None = None) -> Ticket | None:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            query, args = "SELECT * FROM support_tickets WHERE id=%s", [ticket_id]
            if conversation_id is not None:
                query += " AND conversation_id=%s"
                args.append(conversation_id)
            cur.execute(query, args)
            row = cur.fetchone()
            return Ticket.model_validate(row) if row else None

    def update_ticket(
        self, ticket_id: str, status: TicketStatus, conversation_id: str | None = None
    ) -> Ticket | None:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            query, args = (
                "UPDATE support_tickets SET status=%s,updated_at=now() WHERE id=%s",
                [status.value, ticket_id],
            )
            if conversation_id is not None:
                query += " AND conversation_id=%s"
                args.append(conversation_id)
            cur.execute(query + " RETURNING *", args)
            row = cur.fetchone()
            return Ticket.model_validate(row) if row else None

    def tickets(self, limit: int = 50) -> list[dict]:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT t.*,
                (SELECT jsonb_agg(jsonb_build_object('role',m.role,'content',m.content) ORDER BY m.id)
                 FROM support_messages m WHERE m.conversation_id=t.conversation_id) AS messages,
                (SELECT jsonb_agg(r.body ORDER BY r.created_at) FROM support_ticket_replies r WHERE r.ticket_id=t.id) AS replies
                FROM support_tickets t ORDER BY t.created_at DESC LIMIT %s""",
                (limit,),
            )
            return cur.fetchall()

    def reply(self, ticket_id: str, text: str) -> None:
        with connection() as conn:
            if not conn.execute(
                "SELECT 1 FROM support_tickets WHERE id=%s", (ticket_id,)
            ).fetchone():
                raise NotFoundError()
            conn.execute(
                "INSERT INTO support_ticket_replies(ticket_id,body) VALUES (%s,%s)",
                (ticket_id, sanitize(text)),
            )
            conn.execute("UPDATE support_tickets SET updated_at=now() WHERE id=%s", (ticket_id,))
            conn.execute(
                "INSERT INTO support_audit(event,data) VALUES ('staff_reply',%s)",
                (Jsonb({"ticket_id": ticket_id}),),
            )

    def audit(self, event: str, data: dict, principal: str | None = None) -> None:
        with connection() as conn:
            conn.execute(
                "INSERT INTO support_audit(event,principal_hash,data) VALUES (%s,%s,%s)",
                (event, principal, Jsonb(sanitize(data))),
            )

    def save_eval(self, kind: str, report: dict, identifier: str | None = None) -> str:
        identifier = identifier or str(uuid4())
        with connection() as conn:
            conn.execute(
                "INSERT INTO support_eval_runs(id,kind,report) VALUES (%s,%s,%s) ON CONFLICT(id) DO UPDATE SET report=EXCLUDED.report",
                (identifier, kind, Jsonb(sanitize(report))),
            )
        return identifier

    def evaluations(self) -> list[dict]:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id,kind,report,created_at FROM support_eval_runs ORDER BY created_at DESC LIMIT 20"
            )
            return cur.fetchall()

    def recent_turns(self) -> list[dict]:
        with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT request_id,conversation_id,state,error_code,response,trace,created_at FROM support_turns ORDER BY created_at DESC LIMIT 20"
            )
            return cur.fetchall()


def get_repository() -> Repository:
    return Repository()
