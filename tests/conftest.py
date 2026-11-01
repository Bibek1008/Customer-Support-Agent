"""Shared test fixtures and fakes.

These let the guardrail, retrieval, confidence, and loop tests run deterministically
without a network, a GPU, or an API key. The fakes mimic the shapes the real code
consumes: a fake Anthropic ``messages.create`` that replays scripted responses, and
a deterministic bag-of-words embedder so retrieval ranks the right chunks.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any

import pytest


# --- Fake Anthropic response objects -----------------------------------------
@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str
    usage: Usage = field(default_factory=Usage)


class FakeMessages:
    """Replays a queue of scripted responses, one per ``create`` call."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeMessages ran out of scripted responses")
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[FakeResponse]):
        self.messages = FakeMessages(responses)


@pytest.fixture
def make_client():
    """Return a factory that builds a FakeClient from scripted responses."""

    def _factory(responses: list[FakeResponse]) -> FakeClient:
        return FakeClient(responses)

    return _factory


# --- Deterministic embedder ---------------------------------------------------
# Common words carry no topic signal; dropping them keeps disjoint-topic texts
# near-orthogonal under the bag-of-words fake embedder.
_STOPWORDS = {
    "a", "an", "the", "of", "to", "is", "are", "and", "or", "in", "on", "for",
    "you", "your", "we", "it", "within", "after", "any", "how", "long", "do",
    "i", "my", "me", "can", "what", "please", "help", "will", "see", "was",
    "have", "has", "with", "that", "this", "from", "at", "be", "as",
}


class DeterministicEmbedder:
    """Hash content words into a fixed-width bag-of-words vector, L2-normalized.

    Two texts that share content words get similar vectors, so cosine ranking is
    meaningful without any model. Stopwords are dropped so unrelated topics score
    near zero. Good enough to test that retrieval returns the relevant chunk and
    its citation, and returns nothing for an off-topic query.
    """

    dim = 4096

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self._vec(text)

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            if token in _STOPWORDS:
                continue
            idx = int(hashlib.sha1(token.encode()).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


@pytest.fixture
def kb(monkeypatch):
    """Ingest the sample KB with a deterministic embedder into a fresh store."""
    import support_agent.kb.embed as embed_mod
    import support_agent.kb.ingest as ingest_mod
    import support_agent.kb.store as store_mod
    import support_agent.tools.knowledge_base as kb_mod

    fake = DeterministicEmbedder()
    monkeypatch.setattr(embed_mod, "get_embedder", lambda: fake)
    monkeypatch.setattr(ingest_mod, "get_embedder", lambda: fake)
    monkeypatch.setattr(kb_mod, "get_embedder", lambda: fake)

    # Fresh in-memory store for the test.
    store_mod._STORE = None
    ingest_mod.ingest_directory("eval/datasets/kb_docs")
    yield store_mod.get_store()
    store_mod._STORE = None


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Keep spans as no-ops and reset process singletons between tests.

    The safety classifier and ticketing backend cache settings at construction,
    so a test that points them at a different URL must not leak that instance
    into the next test. Resetting the singletons gives each test a clean process.
    """
    monkeypatch.setenv("TRACING_ENABLED", "0")
    from support_agent.config import get_settings

    get_settings.cache_clear()

    import support_agent.guardrails.safety as safety_mod
    import support_agent.kb.store as store_mod
    import support_agent.tools.ticketing as ticketing_mod

    safety_mod._CLASSIFIER = None
    store_mod._STORE = None
    monkeypatch.setattr(store_mod, "_PSYCOPG_AVAILABLE", False)
    ticketing_mod._BACKEND = None
    yield
    safety_mod._CLASSIFIER = None
    store_mod._STORE = None
    ticketing_mod._BACKEND = None
    get_settings.cache_clear()
