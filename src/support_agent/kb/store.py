"""pgvector store.

The KB and the tickets share one Postgres database. Chunks live in ``kb_chunks``
with an HNSW index on the embedding for cosine distance. Retrieval returns the
chunk text *and* its source, because an answer is only allowed to cite chunks it
actually retrieved.

An in-memory fallback is available only when persistence is explicitly disabled,
so isolated tests run without Postgres. The fallback does a brute-force
cosine scan over the ingested chunks; the pgvector path is what runs in
production.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field

from support_agent.config import get_settings

try:
    import psycopg
    from pgvector.psycopg import register_vector

    _PSYCOPG_AVAILABLE = True
except ImportError:  # pragma: no cover - only when psycopg is absent
    _PSYCOPG_AVAILABLE = False


@dataclass
class Chunk:
    source_id: str
    source_title: str
    url: str | None
    text: str
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    active: bool = True
    profile: str = "office_store"


@dataclass
class Retrieved:
    source_id: str
    source_title: str
    url: str | None
    text: str
    score: float  # cosine similarity in [0, 1]
    metadata: dict[str, str] = field(default_factory=dict)
    profile: str = "office_store"


class VectorStore:
    """Store and search chunks. Prefers pgvector; falls back to in-memory."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._conn = None
        self._memory: list[Chunk] = []
        self._use_db = _PSYCOPG_AVAILABLE and self._try_connect()
        if not self._use_db and (
            self.settings.persistence_enabled or self.settings.app_env == "production"
        ):
            raise RuntimeError(
                "PostgreSQL knowledge storage is unavailable; refusing memory fallback."
            )

    # --- connection -----------------------------------------------------------
    def _try_connect(self) -> bool:
        try:
            self._conn = psycopg.connect(
                self.settings.database_url, autocommit=True, connect_timeout=10
            )
            if self.settings.app_env != "production":
                self._ensure_schema()
            register_vector(self._conn)
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT format_type(atttypid,atttypmod) FROM pg_attribute WHERE attrelid='kb_chunks'::regclass AND attname='embedding'"
                )
                if cur.fetchone()[0] != f"vector({self.settings.embedding_dim})":
                    raise RuntimeError(
                        "Knowledge embedding dimension does not match configuration."
                    )
            self._conn.close()
            self._conn = None
            return True
        except (psycopg.Error, RuntimeError, ValueError, TypeError):
            if self._conn is not None:
                self._conn.close()
            self._conn = None
            return False

    @contextmanager
    def _cursor(self):
        from support_agent.db import connection

        with connection() as conn, conn.cursor() as cur:
            yield cur

    def _ensure_schema(self) -> None:
        dim = self.settings.embedding_dim
        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS kb_chunks (
                    id           BIGSERIAL PRIMARY KEY,
                    source_id    TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    url          TEXT,
                    text         TEXT NOT NULL,
                    embedding    vector({dim}) NOT NULL,
                    metadata     JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    content_hash TEXT
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE kb_chunks
                    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                """
            )
            cur.execute("ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS content_hash TEXT")
            cur.execute(
                "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE"
            )
            cur.execute(
                "ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS profile TEXT NOT NULL DEFAULT 'office_store'"
            )
            cur.execute("ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS embedding_provider TEXT")
            cur.execute("ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT")
            cur.execute(
                "UPDATE kb_chunks SET embedding_provider=metadata->>'embedding_provider', embedding_model=metadata->>'embedding_model' WHERE embedding_provider IS NULL OR embedding_model IS NULL"
            )
            cur.execute(
                """
                SELECT source_id, content_hash
                FROM kb_chunks
                WHERE content_hash IS NOT NULL
                """
            )
            seen_hashes = set(cur.fetchall())
            cur.execute(
                """
                SELECT id, source_id, text
                FROM kb_chunks
                WHERE content_hash IS NULL
                ORDER BY id
                """
            )
            for row_id, source_id, text in cur.fetchall():
                content_hash = self._content_hash(text)
                key = (source_id, content_hash)
                if key in seen_hashes:
                    continue
                seen_hashes.add(key)
                cur.execute(
                    "UPDATE kb_chunks SET content_hash = %s WHERE id = %s",
                    (content_hash, row_id),
                )
            cur.execute("DROP INDEX IF EXISTS kb_chunks_source_content_hash")
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS kb_chunks_profile_model_source_hash ON kb_chunks(profile, embedding_provider, embedding_model, source_id, content_hash)"
            )
            if dim <= 2000:
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS kb_chunks_embedding_hnsw ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
                )

    # --- writes ---------------------------------------------------------------
    def upsert(self, chunks: list[Chunk]) -> int:
        """Insert chunks. Returns the count written."""
        if not chunks:
            return 0
        sources = {
            (
                chunk.profile,
                chunk.source_id,
                self.settings.embedding_provider,
                self.settings.embedding_model,
            )
            for chunk in chunks
        }
        if self._use_db:
            with self._cursor() as cur:
                for profile, source, provider, model in sources:
                    cur.execute(
                        "UPDATE kb_chunks SET active=FALSE WHERE profile=%s AND source_id=%s AND embedding_provider=%s AND embedding_model=%s",
                        (profile, source, provider, model),
                    )
                for c in chunks:
                    content_hash = self._content_hash(c.text)
                    cur.execute(
                        """
                        INSERT INTO kb_chunks
                            (profile, embedding_provider, embedding_model, source_id, source_title, url, text, embedding, metadata, content_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s::jsonb, %s)
                        ON CONFLICT (profile, embedding_provider, embedding_model, source_id, content_hash) DO UPDATE SET
                            source_title = EXCLUDED.source_title,
                            url = EXCLUDED.url,
                            text = EXCLUDED.text,
                            embedding = EXCLUDED.embedding,
                            metadata = EXCLUDED.metadata,
                            active = TRUE
                        """,
                        (
                            c.profile,
                            self.settings.embedding_provider,
                            self.settings.embedding_model,
                            c.source_id,
                            c.source_title,
                            c.url,
                            c.text,
                            c.embedding,
                            json.dumps(c.metadata),
                            content_hash,
                        ),
                    )
            return len(chunks)
        for chunk in self._memory:
            if (
                chunk.profile,
                chunk.source_id,
                self.settings.embedding_provider,
                self.settings.embedding_model,
            ) in sources:
                chunk.active = False
        existing = {
            (chunk.profile, chunk.source_id, self._content_hash(chunk.text)): index
            for index, chunk in enumerate(self._memory)
        }
        for chunk in chunks:
            chunk.active = True
            key = (chunk.profile, chunk.source_id, self._content_hash(chunk.text))
            if key in existing:
                self._memory[existing[key]] = chunk
            else:
                existing[key] = len(self._memory)
                self._memory.append(chunk)
        return len(chunks)

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def clear(self, profile: str = "office_store") -> None:
        if self._use_db:
            with self._cursor() as cur:
                cur.execute("UPDATE kb_chunks SET active=FALSE WHERE profile=%s", (profile,))
        for chunk in self._memory:
            if chunk.profile == profile:
                chunk.active = False

    # --- reads ----------------------------------------------------------------
    def search(self, query_embedding: list[float], k: int = 4) -> list[Retrieved]:
        """Return the ``k`` nearest chunks with a cosine similarity score."""
        if self._use_db:
            return self._search_db(query_embedding, k)
        return self._search_memory(query_embedding, k)

    def _search_db(self, q: list[float], k: int) -> list[Retrieved]:
        profile = self._profile()
        with self._cursor() as cur:
            # 1 - cosine_distance = cosine_similarity, clamped to [0, 1].
            cur.execute(
                """
                SELECT source_id, source_title, url, text, metadata,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM kb_chunks
                WHERE active=TRUE AND profile=%s AND embedding_model=%s AND embedding_provider=%s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (q, profile, self.settings.embedding_model, self.settings.embedding_provider, q, k),
            )
            rows = cur.fetchall()
        return [
            Retrieved(
                source_id=r[0],
                source_title=r[1],
                url=r[2],
                text=r[3],
                score=max(0.0, min(1.0, float(r[5]))),
                metadata=r[4] if isinstance(r[4], dict) else json.loads(r[4]),
                profile=profile,
            )
            for r in rows
        ]

    def _search_memory(self, q: list[float], k: int) -> list[Retrieved]:
        def cosine(a: list[float], b: list[float]) -> float:
            # Vectors are stored L2-normalized, so cosine is the dot product.
            return sum(x * y for x, y in zip(a, b))

        scored = [
            Retrieved(
                source_id=c.source_id,
                source_title=c.source_title,
                url=c.url,
                text=c.text,
                score=max(0.0, min(1.0, cosine(q, c.embedding))),
                metadata=c.metadata,
            )
            for c in self._memory
            if c.active and c.profile == self._profile()
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]

    @staticmethod
    def _profile() -> str:
        from support_agent.request_context import current_request

        request = current_request.get()
        return request.kb_profile if request else "office_store"

    def count(self, profile: str | None = None) -> int:
        profile = profile or self._profile()
        if self._use_db:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM kb_chunks WHERE active=TRUE AND profile=%s AND embedding_model=%s AND embedding_provider=%s",
                    (profile, self.settings.embedding_model, self.settings.embedding_provider),
                )
                return int(cur.fetchone()[0])
        return sum(chunk.active and chunk.profile == profile for chunk in self._memory)


_STORE: VectorStore | None = None


def get_store() -> VectorStore:
    global _STORE
    if _STORE is None:
        _STORE = VectorStore()
    return _STORE


def dump_memory(path: str) -> None:
    """Persist the in-memory store to JSON (used by ingest when no DB is up)."""
    store = get_store()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([c.__dict__ for c in store._memory], fh)
