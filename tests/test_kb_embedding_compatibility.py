"""The active policy profile and configured embedding space stay isolated."""

from contextlib import contextmanager

from support_agent.config import get_settings
from support_agent.kb.store import VectorStore


def test_vector_search_filters_demo_profile_provider_and_model(monkeypatch):
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
    assert store.search([0.0] * 384) == []

    assert "COALESCE(metadata->>'profile','') IN ('','office_store')" in executed["query"]
    assert executed["params"][1:3] == ("BAAI/bge-small-en-v1.5", "fastembed")
