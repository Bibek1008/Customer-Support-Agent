"""Embedding client.

Default is the hosted ``text-embedding-3-large`` (3072-dim, MTEB avg 64.6,
Matryoshka truncation via the ``dimensions`` argument). The self-host option is
BAAI ``bge-m3`` (1024-dim dense, 8192-token input). Which one is used is set by
``EMBEDDING_PROVIDER``; the rest of the KB code does not care which.

Gemini hosted embeddings and FastEmbed CPU embeddings are also available.
All providers return unit-length vectors so cosine distance in pgvector is a
plain inner product.
"""

from __future__ import annotations

import math
from functools import lru_cache

import httpx

from support_agent.config import get_settings
from support_agent.observability.tracing import embedding_span


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
        if self.provider == "fastembed":
            return self._embed_fastembed(texts)
        if self.provider == "gemini":
            return self._embed_gemini(texts, task_type="RETRIEVAL_DOCUMENT")
        raise ValueError(f"Unknown embedding provider {self.provider!r}")

    def embed_one(self, text: str) -> list[float]:
        if self.provider == "gemini":
            return self._embed_gemini([text], task_type="RETRIEVAL_QUERY")[0]
        return self.embed([text])[0]

    def _embed_gemini(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        with embedding_span(
            self.settings.embedding_model, input=texts, task_type=task_type
        ) as span:
            vectors = self._request_gemini(texts, task_type=task_type, span=span)
            span.update(output={"vector_count": len(vectors), "dimensions": self.dim})
            return vectors

    def _request_gemini(self, texts: list[str], *, task_type: str, span) -> list[list[float]]:
        if not self.settings.gemini_api_key:
            raise RuntimeError("Set GEMINI_API_KEY in .env to use Gemini embeddings.")
        if not 128 <= self.dim <= 3072:
            raise ValueError("Gemini embedding dimension must be between 128 and 3072.")
        model = self.settings.embedding_model.removeprefix("models/")
        vectors = []
        input_tokens = 0
        usage_available = False
        for start in range(0, len(texts), 100):
            batch = texts[start : start + 100]
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents",
                headers={"x-goog-api-key": self.settings.gemini_api_key},
                json={
                    "requests": [
                        {
                            "model": f"models/{model}",
                            "content": {"parts": [{"text": text}]},
                            "taskType": task_type,
                            "outputDimensionality": self.dim,
                        }
                        for text in batch
                    ]
                },
                timeout=60.0,
            )
            if response.status_code == 429:
                raise RuntimeError("Gemini embedding quota reached; wait before retrying.")
            if response.is_error:
                # Provider error bodies can contain source documents. Do not expose them.
                raise RuntimeError(
                    f"Gemini embedding request failed (HTTP {response.status_code})."
                )
            data = response.json()
            usage = data.get("usageMetadata", {})
            if "promptTokenCount" in usage:
                input_tokens += int(usage["promptTokenCount"])
                usage_available = True
            embeddings = data.get("embeddings", [])
            if len(embeddings) != len(batch):
                raise RuntimeError("Gemini returned an incomplete batch of embeddings.")
            for item in embeddings:
                vector = [float(value) for value in item["values"]]
                if len(vector) != self.dim or not all(math.isfinite(value) for value in vector):
                    raise RuntimeError("Gemini returned an invalid embedding vector.")
                vectors.append(_l2_normalize(vector))
        span.update(metadata={"usage_available": usage_available})
        if usage_available:
            span.update(usage_details={"input": input_tokens})
        return vectors

    # --- Hosted default -------------------------------------------------------
    def _embed_fastembed(self, texts: list[str]) -> list[list[float]]:
        if self._local_model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise RuntimeError("Install the 'free' extra to use CPU embeddings.") from exc
            self._local_model = TextEmbedding(
                model_name=self.settings.embedding_model, cache_dir=".cache/fastembed"
            )
        vectors = [list(map(float, vector)) for vector in self._local_model.embed(texts)]
        if any(len(vector) != self.dim for vector in vectors):
            raise ValueError("EMBEDDING_DIM must match the local embedding model's dimension.")
        return [_l2_normalize(vector) for vector in vectors]

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
