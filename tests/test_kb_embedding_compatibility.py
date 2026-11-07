"""Verify pgvector retrieval remains isolated by profile and embedding space."""

from contextlib import contextmanager

from support_agent.config import get_settings
from support_agent.kb.store import VectorStore
from support_agent.request_context import RequestContext, current_request


def test_vector_search_filters_profile_provider_and_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    get_settings.cache_clear()
    store = VectorStore.__new__(VectorStore)
    store.settings = get_settings()
    store._use_db = True
    executed = {}

    class Cursor:
        def execute(self, query, params):
            executed["query"] = query
            executed["params"] = params

        def fetchall(self):
            return []

    @contextmanager
    def cursor():
        yield Cursor()

    store._cursor = cursor
    request_token = current_request.set(
        RequestContext("conversation", "request", "owner", kb_profile="olist_demo")
    )
    try:
        assert store.search([0.0] * 384) == []
    finally:
        current_request.reset(request_token)

    query = executed["query"]
    assert "profile=%s AND embedding_model=%s AND embedding_provider=%s" in query
    assert executed["params"][1:4] == (
        "olist_demo",
        "BAAI/bge-small-en-v1.5",
        "fastembed",
    )
