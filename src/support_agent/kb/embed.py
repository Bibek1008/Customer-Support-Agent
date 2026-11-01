"""Embedding client.

Default is the hosted ``text-embedding-3-large`` (3072-dim, MTEB avg 64.6,
Matryoshka truncation via the ``dimensions`` argument). The self-host option is
BAAI ``bge-m3`` (1024-dim dense, 8192-token input). Which one is used is set by
``EMBEDDING_PROVIDER``; the rest of the KB code does not care which.

Both providers return unit-length vectors so cosine distance in pgvector is a
plain inner product.
"""

from __future__ import annotations

import math
from functools import lru_cache

import httpx

from support_agent.config import get_settings


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


class Embedder:
    """Embed text into vectors for retrieval. One instance per process."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = self.settings.embedding_provider
        self.dim = self.settings.embedding_dim
        self._local_model = None  # lazily built for the bge-m3 path

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input string."""
        if not texts:
            return []
        if self.provider == "openai":
            return self._embed_openai(texts)
        if self.provider == "bge-m3":
            return self._embed_bge_m3(texts)
        raise ValueError(f"Unknown embedding provider {self.provider!r}")

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    # --- Hosted default -------------------------------------------------------
    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        if not self.settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Set it, or switch "
                "EMBEDDING_PROVIDER=bge-m3 to embed locally."
            )
        resp = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            json={
                "model": self.settings.embedding_model,
                "input": texts,
                # Matryoshka truncation: ask for exactly the stored dimension.
                "dimensions": self.dim,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # The API returns items in request order.
        return [_l2_normalize(item["embedding"]) for item in data]

    # --- Self-host option -----------------------------------------------------
    def _embed_bge_m3(self, texts: list[str]) -> list[list[float]]:
        model = self._get_local_model()
        # BGEM3FlagModel returns a dict with a "dense_vecs" numpy array.
        out = model.encode(texts, return_dense=True, return_sparse=False)
        vecs = out["dense_vecs"]
        return [_l2_normalize(list(map(float, v))) for v in vecs]

    def _get_local_model(self):
        if self._local_model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as exc:  # pragma: no cover - optional extra
                raise RuntimeError(
                    "bge-m3 selected but FlagEmbedding is not installed. "
                    "Install the 'local-embed' extra."
                ) from exc
            self._local_model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
        return self._local_model


@lru_cache
def get_embedder() -> Embedder:
    return Embedder()
