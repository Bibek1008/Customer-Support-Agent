"""Verify retrieval tasks, batch alignment, and failures without external APIs."""

import httpx
import pytest

from support_agent.kb.embed import Embedder


@pytest.fixture
def embedder(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from support_agent.config import get_settings

    get_settings.cache_clear()
    return Embedder()


def test_batches_keep_order_and_queries_use_query_task(embedder, monkeypatch):
    requests = []

    def post(url, **kwargs):
        assert url.endswith("/models/gemini-embedding-001:batchEmbedContents")
        assert kwargs["headers"] == {"x-goog-api-key": "test-key"}
        batch = kwargs["json"]["requests"]
        requests.append(batch)
        return httpx.Response(
            200, json={"embeddings": [{"values": [3, 4] + [0] * 382} for _ in batch]}
        )

    monkeypatch.setattr(httpx, "post", post)
    assert len(embedder.embed([f"document {i}" for i in range(101)])) == 101
    assert [len(batch) for batch in requests] == [100, 1]
    assert requests[1][0]["content"]["parts"][0]["text"] == "document 100"
    assert requests[0][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert requests[0][0]["outputDimensionality"] == 384
    vector = embedder.embed_one("returns")
    assert vector[:2] == [0.6, 0.8]
    assert requests[-1][0]["taskType"] == "RETRIEVAL_QUERY"


@pytest.mark.parametrize("body", [{"embeddings": []}, {"embeddings": [{"values": [1]}]}])
def test_invalid_response_cannot_be_stored(embedder, monkeypatch, body):
    monkeypatch.setattr(httpx, "post", lambda *_, **__: httpx.Response(200, json=body))
    with pytest.raises(RuntimeError):
        embedder.embed(["document"])


@pytest.mark.parametrize("status", [400, 403, 429])
def test_errors_do_not_expose_documents(embedder, monkeypatch, status):
    monkeypatch.setattr(
        httpx, "post", lambda *_, **__: httpx.Response(status, text="sensitive document")
    )
    with pytest.raises(RuntimeError) as error:
        embedder.embed(["document"])
    assert "sensitive" not in str(error.value)
