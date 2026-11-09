"""Retrieval tool over the pgvector knowledge base.

The tool embeds the query, searches the vector store, and returns the top chunks
*with their sources*. The agent may only cite chunks this tool returned, so the
citations it produces are the same objects the confidence and hallucination
checks score against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from support_agent.kb.embed import get_embedder
from support_agent.kb.store import get_store
from support_agent.schemas import Citation

# Chunks below this similarity are dropped, so a query with nothing relevant
# returns no citations rather than weak ones (which keeps the confidence score grounded).
_MIN_SIMILARITY = 0.20
_QUERY_STOPWORDS = {
    "about",
    "after",
    "are",
    "can",
    "could",
    "does",
    "for",
    "from",
    "have",
    "help",
    "how",
    "is",
    "me",
    "my",
    "period",
    "please",
    "system",
    "systems",
    "tell",
    "the",
    "their",
    "this",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "would",
    "you",
    "your",
}


def _terms(text: str) -> set[str]:
    """Return lightweight normalized terms to reject topic-unrelated vector hits."""
    normalized = set()
    for token in re.findall(r"[a-z0-9]{3,}", text.lower()):
        if token in _QUERY_STOPWORDS:
            continue
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        normalized.add(token)
    return normalized


@dataclass
class KBResult:
    text: str  # human-readable block for the model, with numbered sources
    citations: list[Citation]


def search_knowledge_base(query: str, k: int = 4) -> KBResult:
    """Retrieve the top ``k`` KB chunks for ``query``."""
    embedder = get_embedder()
    store = get_store()
    q_vec = embedder.embed_one(query)
    hits = store.search(q_vec, k=k)

    citations: list[Citation] = []
    lines: list[str] = []
    query_terms = _terms(query)
    for i, hit in enumerate(hits):
        if hit.score < _MIN_SIMILARITY or not (query_terms & _terms(hit.text)):
            continue
        citation = Citation(
            source_id=hit.source_id,
            source_title=hit.source_title,
            url=hit.url,
            chunk=hit.text,
            score=hit.score,
        )
        citations.append(citation)
        lines.append(f"[{i + 1}] {hit.source_title} (score {hit.score:.2f})\n{hit.text}")

    if not citations:
        text = (
            "No knowledge base article matched this query closely enough to cite. "
            "Do not answer from memory. Say you don't know from the available information; "
            "ask for details or offer staff review without automatically opening a ticket."
        )
    else:
        text = "Retrieved knowledge base chunks:\n\n" + "\n\n".join(lines)

    return KBResult(text=text, citations=citations)
