"""Capture guardrail decisions for the local database as well as Langfuse."""

from contextlib import contextmanager
from contextvars import ContextVar

_events: ContextVar[list | None] = ContextVar("support_audit_events", default=None)


@contextmanager
def capture_events():
    events = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)


def record_guardrail(check: str, metadata: dict) -> None:
    events = _events.get()
    if events is not None:
        events.append({"check": check, **metadata})
