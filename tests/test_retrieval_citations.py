"""Every retrieved answer maps to a real KB chunk, and the citation carries its
source. Uses the deterministic embedder + the sample KB (the ``kb`` fixture)."""

from __future__ import annotations

from support_agent.tools.knowledge_base import search_knowledge_base
from support_agent.tools.registry import dispatch


def test_returns_query_retrieves_returns_policy(kb):
    result = search_knowledge_base("how long is the return window for a refund", k=4)
    assert result.citations, "expected at least one citation"
    top = result.citations[0]
    assert top.source_id == "returns-policy"
    assert "30 days" in top.chunk
    # Citations carry their source so an answer can attribute the claim.
    assert top.source_title
    assert 0.0 <= top.score <= 1.0


def test_shipping_query_retrieves_shipping_doc(kb):
    result = search_knowledge_base("how fast is standard shipping", k=4)
    assert result.citations
    assert any(c.source_id == "shipping" for c in result.citations)


def test_unmatched_query_returns_no_citations(kb):
    # Nothing in the KB is about astrophysics; retrieval should not invent a cite.
    result = search_knowledge_base("orbital mechanics of binary star systems", k=4)
    assert result.citations == []
    assert "do not answer from memory" in result.text.lower()


def test_dispatch_carries_citations(kb):
    outcome = dispatch("knowledge_base", {"query": "return window", "k": 3})
    assert outcome.citations
    assert all(c.chunk for c in outcome.citations)


def test_reingestion_is_idempotent_and_preserves_source_metadata(kb):
    from support_agent.kb.ingest import ingest_directory

    initial_count = kb.count()
    ingest_directory("eval/datasets/kb_docs")

    assert kb.count() == initial_count
    warranty = next(chunk for chunk in kb._memory if chunk.source_id == "warranty")
    assert warranty.metadata["title"] == "Product Warranty"
    assert warranty.metadata["url"] == "https://help.example.com/warranty"
    assert warranty.metadata["source_path"] == "warranty.md"
