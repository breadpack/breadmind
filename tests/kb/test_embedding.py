"""Unit tests for KBEmbedder dim alignment."""
from __future__ import annotations

from breadmind.kb.embedding import KB_EMBEDDING_DIM, KBEmbedder


class _FixedInner:
    def __init__(self, vec: list[float] | None) -> None:
        self._vec = vec

    async def encode(self, text: str) -> list[float] | None:
        return self._vec


async def test_kb_embedder_pads_short_vectors_to_target_dim():
    inner = _FixedInner([0.1] * 384)
    embedder = KBEmbedder(inner)
    out = await embedder.encode("hello")
    assert len(out) == KB_EMBEDDING_DIM
    assert out[:384] == [0.1] * 384
    assert all(v == 0.0 for v in out[384:])


async def test_kb_embedder_truncates_long_vectors_to_target_dim():
    inner = _FixedInner([0.5] * 1536)
    embedder = KBEmbedder(inner)
    out = await embedder.encode("hello")
    assert len(out) == KB_EMBEDDING_DIM
    assert out == [0.5] * KB_EMBEDDING_DIM


async def test_kb_embedder_falls_back_when_inner_returns_none():
    inner = _FixedInner(None)
    embedder = KBEmbedder(inner)
    out = await embedder.encode("hello world")
    assert len(out) == KB_EMBEDDING_DIM
    # Deterministic: same text => same vector.
    out2 = await embedder.encode("hello world")
    assert out == out2


async def test_kb_embedder_passes_through_when_inner_matches_dim():
    vec = [float(i) / 1024.0 for i in range(KB_EMBEDDING_DIM)]
    embedder = KBEmbedder(_FixedInner(vec))
    out = await embedder.encode("hello")
    assert out == vec
