"""Embeddings via OpenRouter, plus a deterministic test embedder.

Live: nvidia/nemotron-3.5-embed-1b:free (2048 dims), sent in batches.
Rate limits surface as RateLimitError with a clear message for the user.

Test/dev (no key): HashEmbedder — a bag-of-words hash vector. It is NOT a
real embedding model; it only exists so tests and the eval script can run
the retrieval pipeline without a key. It is never used when a key is set.
"""
import hashlib
import math

from . import http_client
from .config import settings

EMBED_DIMS = 2048


class RateLimitError(RuntimeError):
    pass


class AIError(RuntimeError):
    pass


class OpenRouterEmbedder:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.openrouter_embed_model
        if not self.api_key:
            raise AIError(
                "OPENROUTER_API_KEY is not set. Add it to .env (see README) "
                "or run with REVIEW_FALLBACK=rule_based for the eval script."
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches. Returns one 2048-dim vector per text."""
        out: list[list[float]] = []
        batch_size = settings.embed_batch_size
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = http_client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": batch},
                timeout=120,
            )
            if resp.status_code == 429:
                raise RateLimitError(
                    "OpenRouter rate limit reached. Please wait a minute and retry."
                )
            if resp.status_code >= 400:
                raise AIError(f"Embedding request failed ({resp.status_code}): {resp.text[:300]}")
            data = resp.json()["data"]
            # OpenRouter returns embeddings in request order.
            for row in sorted(data, key=lambda r: r["index"]):
                vec = row["embedding"]
                if len(vec) != EMBED_DIMS:
                    raise AIError(f"Expected {EMBED_DIMS} dims, got {len(vec)}")
                out.append([float(v) for v in vec])
        return out


class HashEmbedder:
    """Deterministic bag-of-words hash vectors (tests/eval only, no key needed).

    Each word hashes into one of 2048 buckets; the vector is L2-normalised.
    Texts sharing words get similar vectors, so retrieval behaves sensibly
    in tests. This is not a semantic embedding — never use it for real reviews.
    """

    def __init__(self, dims: int = EMBED_DIMS):
        self.dims = dims

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for word in text.lower().split():
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dims
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def get_embedder():
    """Live embedder when a key is set, hash embedder otherwise (tests only)."""
    if settings.openrouter_api_key:
        return OpenRouterEmbedder()
    return HashEmbedder()
