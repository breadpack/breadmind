"""Backfill-test fixtures: fake redactor and fake/exploding embedder."""
from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class FakeRedactor:
    """Pass-through redactor. ``abort_if_secrets`` is a no-op; ``redact`` returns input."""

    async def abort_if_secrets(self, text: str) -> None:
        return None

    async def redact(self, text: str, session_id: str) -> tuple[str, str]:
        return text, "map-id"


# pgvector dimension matches migration 004_org_kb (org_knowledge.embedding).
EMBED_DIM = 1024


@dataclass
class FakeEmbedder:
    """Deterministic embedder: returns a fixed-dim list derived from text length."""

    async def encode(self, text: str) -> list[float]:
        base = (len(text) % 100) / 100.0
        return [base] * EMBED_DIM


@dataclass
class ExplodingEmbedder:
    """Raises on every encode after the first call."""

    calls: int = 0

    async def encode(self, text: str) -> list[float]:
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("simulated embed failure")
        return [0.1] * EMBED_DIM


@pytest.fixture
def fake_redactor() -> FakeRedactor:
    return FakeRedactor()


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def exploding_embedder() -> ExplodingEmbedder:
    return ExplodingEmbedder()
