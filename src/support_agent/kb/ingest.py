"""Chunk KB documents, embed them, and upsert into the vector store.

Run as a module::

    python -m support_agent.kb.ingest --docs eval/datasets/kb_docs

Each file in the docs directory becomes one source; its text is split into
overlapping chunks so a retrieved chunk still carries enough context to cite. A
document may start with a YAML-ish front matter block giving ``title`` and
``url``; otherwise the filename is the title and the URL is left empty.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from support_agent.kb.embed import get_embedder
from support_agent.kb.profiles import PROFILES, validate_document
from support_agent.kb.store import Chunk, get_store

_FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Return ``(meta, body)``. Supports a tiny ``key: value`` front matter."""
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, text[match.end() :]


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries, then pack paragraphs into ~``size``-char
    chunks with ``overlap`` characters of carry-over for context."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(buf) + len(para) + 1 <= size:
            buf = f"{buf}\n{para}".strip()
        else:
            if buf:
                chunks.append(buf)
            # Start the next chunk with a tail of the previous one for context.
            tail = buf[-overlap:] if overlap and buf else ""
            buf = f"{tail}\n{para}".strip() if tail else para
    if buf:
        chunks.append(buf)
    return chunks


def ingest_directory(
    docs_dir: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
    profile: str = "office_store",
) -> int:
    """Ingest every Markdown/text file under ``docs_dir`` and return chunks processed."""
    store = get_store()
    embedder = get_embedder()
    settings = store.settings
    if profile not in PROFILES:
        raise ValueError("Unsupported KB profile.")
    chunk_size = chunk_size if chunk_size is not None else settings.kb_chunk_size
    overlap = overlap if overlap is not None else settings.kb_chunk_overlap
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Chunk size must be positive and overlap must be in [0, chunk size).")

    root = Path(docs_dir)
    files = sorted([*root.rglob("*.md"), *root.rglob("*.txt")])
    if not files:
        raise FileNotFoundError(f"No .md/.txt files under {docs_dir!r}")

    all_chunks: list[Chunk] = []
    for path in files:
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        validate_document(profile, meta)
        title = meta.get("title", path.stem.replace("-", " ").title())
        url = meta.get("url") or None
        source_id = path.relative_to(root).with_suffix("").as_posix()
        metadata = {
            **meta,
            "source_path": path.relative_to(root).as_posix(),
            "embedding_model": settings.embedding_model,
            "embedding_provider": settings.embedding_provider,
        }
        for piece in chunk_text(body, size=chunk_size, overlap=overlap):
            all_chunks.append(
                Chunk(
                    source_id=source_id,
                    source_title=title,
                    url=url,
                    text=piece,
                    metadata=metadata,
                    profile=profile,
                )
            )

    # Embed in one batch so provider round-trips are minimized.
    vectors = embedder.embed([c.text for c in all_chunks])
    for chunk, vec in zip(all_chunks, vectors):
        chunk.embedding = vec

    written = store.upsert(all_chunks)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest KB docs into pgvector.")
    parser.add_argument("--docs", default=None, help="Directory of approved KB documents")
    parser.add_argument("--chunk-size", type=int, default=None, help="Chunk size in characters")
    parser.add_argument(
        "--chunk-overlap", type=int, default=None, help="Chunk overlap in characters"
    )
    parser.add_argument("--reset", action="store_true", help="Clear existing chunks first")
    parser.add_argument("--profile", choices=PROFILES, default="office_store")
    args = parser.parse_args()

    settings = get_store().settings
    docs_dir = args.docs or settings.kb_docs_path
    store = get_store()
    if args.reset:
        store.clear(profile=args.profile)

    written = ingest_directory(
        docs_dir,
        chunk_size=args.chunk_size,
        overlap=args.chunk_overlap,
        profile=args.profile,
    )
    print(f"Ingested {written} chunks from {docs_dir} (store now holds {store.count()}).")


if __name__ == "__main__":
    main()
