"""Retrieval tool over the pgvector knowledge base.

The tool embeds the query, searches the vector store, and returns the top chunks
*with their sources*. The agent may only cite chunks this tool returned, so the
citations it produces are the same objects the confidence and hallucination
checks score against.
"""

from __future__ import annotations

from dataclasses import dataclass

from support_agent.kb.embed import get_embedder
from support_agent.kb.store import get_store
from support_agent.schemas import Citation

# Chunks below this similarity are dropped, so a query with nothing relevant
# returns no citations rather than weak ones (which keeps the confidence score grounded).
_MIN_SIMILARITY = 0.20


@dataclass
class KBResult:
    text: str  # human-readable block for the model, with numbered sources
    citations: list[Citation]
    unavailable_reason: str | None = None


def search_knowledge_base(query: str, k: int = 4) -> KBResult:
    from support_agent.request_context import current_request

    context = current_request.get()
    if context and context.kb_profile == "olist_demo":
        return _search(
            query, k, ("brazil_consumer_law", "olist_transaction_profile", "olist_demo_policy")
        )
    return _search(query, k, ("office_store",))


def search_consumer_policy(query: str, k: int = 4) -> KBResult:
    return _search(query, k, ("brazil_consumer_law",))


def _search(query: str, k: int, profiles: tuple[str, ...]) -> KBResult:
    """Retrieve the top ``k`` KB chunks for ``query``."""
    store = get_store()
    if not any(store.count(profile=profile) for profile in profiles):
        return KBResult(
            text="The requested knowledge profiles have not been initialized for the configured embedding model. Do not substitute Office Store policies or answer from memory. Explain that the knowledge base setup is incomplete.",
            citations=[],
            unavailable_reason="knowledge_profile_not_initialized",
        )
    embedder = get_embedder()
    q_vec = embedder.embed_one(query)
    hits = sorted(
        (h for profile in profiles for h in store.search(q_vec, k=k, profile=profile)),
        key=lambda h: h.score,
        reverse=True,
    )[:k]

    citations: list[Citation] = []
    lines: list[str] = []
    for i, hit in enumerate(hits):
        if hit.score < _MIN_SIMILARITY:
            continue
        if hit.profile == "brazil_consumer_law":
            from support_agent.kb.profiles import validate_document

            try:
                validate_document(hit.profile, hit.metadata)
            except ValueError:
                continue
        provenance = hit.metadata.get("source_kind", "demonstration_assumption")
        context = "\nSource type: " + provenance + "; profile: " + hit.profile
        if hit.profile == "brazil_consumer_law":
            context += "; jurisdiction: BR; section: " + hit.metadata["section"]
            context += "; authority: " + hit.metadata["authority"]
            context += "; source URL: " + (hit.url or hit.metadata["url"])
            context += "; retrieved: " + hit.metadata["retrieved_at"]
            context += "; content version: " + hit.metadata["content_version"]
            context += "; verification status: " + hit.metadata["status"]
            context += "; general Brazilian law, not Olist merchant terms or an individual eligibility decision."
        citation = Citation(
            source_id=hit.source_id,
            source_title=hit.source_title,
            url=hit.url,
            chunk=hit.text + context,
            score=hit.score,
            provenance=provenance,
            profile=hit.profile,
            metadata=hit.metadata,
        )
        citations.append(citation)
        lines.append(f"[{i + 1}] {hit.source_title} (score {hit.score:.2f})\n{citation.chunk}")

    if not citations:
        text = (
            "No knowledge base article matched this query closely enough to cite. "
            "Do not answer from memory. Say you don't know from the available information; "
            "ask for details or offer staff review without automatically opening a ticket."
        )
    else:
        text = "Retrieved knowledge base chunks:\n\n" + "\n\n".join(lines)

    return KBResult(text=text, citations=citations)
