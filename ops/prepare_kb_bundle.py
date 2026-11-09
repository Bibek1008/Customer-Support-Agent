"""Prepare a local FastEmbed KB package for review; never connects to a database."""

import json
from dataclasses import asdict
from pathlib import Path

from support_agent.config import get_settings
from support_agent.kb.embed import Embedder
from support_agent.kb.ingest import _parse_front_matter, chunk_text
from support_agent.kb.profiles import validate_document
from support_agent.kb.store import Chunk


def main():
    settings = get_settings().model_copy(
        update={
            "embedding_provider": "fastembed",
            "embedding_model": "BAAI/bge-small-en-v1.5",
            "embedding_dim": 384,
        }
    )
    sources = {
        "brazil_consumer_law": Path("knowledge_base/brazil_consumer_law"),
        "olist_transaction_profile": Path("knowledge_base/olist_demo"),
        "olist_demo_policy": Path("knowledge_base/olist_demo_policy"),
        "office_store": Path("knowledge_base/approved"),
    }
    chunks = []
    for profile, root in sources.items():
        for path in sorted(root.glob("*.md")):
            meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
            validate_document(profile, meta)
            metadata = {
                **meta,
                "source_path": path.name,
                "embedding_provider": settings.embedding_provider,
                "embedding_model": settings.embedding_model,
            }
            chunks.extend(
                Chunk(
                    source_id=path.stem,
                    source_title=meta.get("title", path.stem),
                    url=meta.get("url"),
                    text=text,
                    metadata=metadata,
                    profile=profile,
                )
                for text in chunk_text(body, settings.kb_chunk_size, settings.kb_chunk_overlap)
            )
    embedder = Embedder()
    embedder.settings, embedder.provider, embedder.dim = settings, "fastembed", 384
    for chunk, vector in zip(chunks, embedder.embed([c.text for c in chunks]), strict=True):
        chunk.embedding = vector
    question = "What does general Brazilian consumer law say about online return rights and the withdrawal period?"
    query = embedder.embed_one(question)
    ranked = sorted(
        (
            {
                "source_id": c.source_id,
                "title": c.source_title,
                "score": round(sum(a * b for a, b in zip(query, c.embedding, strict=True)), 4),
                "section": c.metadata["section"],
            }
            for c in chunks
            if c.profile == "brazil_consumer_law"
        ),
        key=lambda c: c["score"],
        reverse=True,
    )
    output = Path(".cache/kb-fastembed-package.json")
    output.write_text(
        json.dumps(
            {
                "embedding_provider": "fastembed",
                "embedding_model": settings.embedding_model,
                "dimension": 384,
                "chunks": [asdict(c) for c in chunks],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "package": str(output),
                "bytes": output.stat().st_size,
                "profile_counts": {p: sum(c.profile == p for c in chunks) for p in sources},
                "legal_query_top_hits": ranked[:3],
                "database_writes": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
