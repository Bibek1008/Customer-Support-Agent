"""Request ownership for tool authorization; never accept identity from the LLM."""

import time
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    conversation_id: str
    request_id: str
    owner_hash: str
    deadline: float = 0.0
    kb_profile: str = "office_store"
    olist_account: str | None = None


current_request: ContextVar[RequestContext | None] = ContextVar("support_request", default=None)


class TurnTimeoutError(TimeoutError):
    pass


def remaining_timeout(maximum: float = 45.0) -> float:
    request = current_request.get()
    if request is None or not request.deadline:
        return maximum
    remaining = request.deadline - time.monotonic()
    if remaining <= 0:
        raise TurnTimeoutError("Support request deadline exceeded.")
    return min(remaining, maximum)
