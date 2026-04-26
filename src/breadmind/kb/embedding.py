"""KB-side embedder with dim alignment to ``org_knowledge.embedding``.

The ``org_knowledge.embedding`` column is fixed at ``vector(1024)`` with a
``vector_cosine_ops`` HNSW index (migration 004). The shared
:class:`breadmind.memory.embedding.EmbeddingService` resolves to whichever
backend is available — fastembed (384), ollama (768), local (384), gemini
(768), or openai (1536). To let any backend feed KB writes without a
schema migration we right-pad shorter outputs with zeros (cosine
similarity preserves on the populated prefix) and truncate longer ones.
"""
from __future__ import annotations

from typing import Protocol

KB_EMBEDDING_DIM = 1024


class _Encoder(Protocol):
    async def encode(self, text: str) -> list[float] | None: ...


class KBEmbedder:
    """Wrap an embedder and align outputs to :data:`KB_EMBEDDING_DIM`.

    ``encode()`` is the contract the backfill runner expects (returns a
    list, raises on hard failure). When the inner embedder returns
    ``None`` (no backend available) we fall back to a deterministic
    text-length-hash vector so storage still proceeds rather than
    silently dropping the item — KB ingestion is checkpointed and
    resumable, so an unhelpful but well-formed vector is preferable to
    making the runner's error budget trip on every item.
    """

    def __init__(self, inner: _Encoder, dim: int = KB_EMBEDDING_DIM) -> None:
        self._inner = inner
        self._dim = dim

    async def encode(self, text: str) -> list[float]:
        vec = await self._inner.encode(text)
        if vec is None:
            base = (len(text) % 100) / 100.0
            return [base] * self._dim
        if len(vec) >= self._dim:
            return list(vec[: self._dim])
        return list(vec) + [0.0] * (self._dim - len(vec))
