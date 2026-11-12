from __future__ import annotations

import hashlib
import math
import random
from functools import lru_cache

from app.config import settings

def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return [0.0] * len(values)
    return [value / norm for value in values]

def _fake_embedding(text: str) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    vector = [rng.uniform(-1.0, 1.0) for _ in range(settings.embedding_dimensions)]
    return _normalize(vector)

@lru_cache(maxsize=1)
def _ollama_client():
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )

def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    if settings.embedding_backend == "fake":
        vectors = [_fake_embedding(text) for text in texts]
    else:
        vectors = _ollama_client().embed_documents(list(texts))

    if len(vectors) != len(texts):
        raise ValueError("embedding provider returned an unexpected number of vectors")

    normalized: list[list[float]] = []
    for vector in vectors:
        values = [float(value) for value in vector]
        if len(values) != settings.embedding_dimensions:
            raise ValueError(
                f"embedding dimension mismatch: expected {settings.embedding_dimensions}, "
                f"got {len(values)}"
            )
        normalized.append(_normalize(values))
    return normalized

def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]

__all__ = ["embed_query", "embed_texts"]
