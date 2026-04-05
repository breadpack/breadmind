"""Tests for hybrid memory search (vector + FTS)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from breadmind.memory.hybrid_search import (
    HybridSearchEngine,
    SearchResult,
    SimpleTextFTS,
)


@pytest.fixture
def mock_vector_backend() -> AsyncMock:
    backend = AsyncMock()
    backend.search.return_value = [
        ("doc about kubernetes", 0.9, {"id": 1}),
        ("doc about docker", 0.7, {"id": 2}),
        ("doc about python", 0.5, {"id": 3}),
    ]
    return backend


@pytest.fixture
def mock_fts_backend() -> AsyncMock:
    backend = AsyncMock()
    backend.search.return_value = [
        ("doc about kubernetes", 0.8, {"id": 1}),
        ("doc about helm charts", 0.6, {"id": 4}),
    ]
    return backend


class TestHybridSearchEngine:
    async def test_hybrid_search_combines_results(
        self, mock_vector_backend: AsyncMock, mock_fts_backend: AsyncMock
    ) -> None:
        engine = HybridSearchEngine(
            vector_backend=mock_vector_backend, fts_backend=mock_fts_backend
        )
        results = await engine.search("kubernetes", limit=10)

        assert len(results) > 0
        # kubernetes doc should be top since it appears in both
        assert results[0].content == "doc about kubernetes"
        assert results[0].source == "both"

    async def test_hybrid_search_vector_only_fallback(
        self, mock_vector_backend: AsyncMock
    ) -> None:
        engine = HybridSearchEngine(vector_backend=mock_vector_backend)
        results = await engine.search("kubernetes", limit=10)

        assert len(results) == 3
        assert all(r.source == "vector" for r in results)

    async def test_hybrid_search_fts_only_fallback(
        self, mock_fts_backend: AsyncMock
    ) -> None:
        engine = HybridSearchEngine(fts_backend=mock_fts_backend)
        results = await engine.search("kubernetes", limit=10)

        assert len(results) == 2
        assert all(r.source == "fts" for r in results)

    async def test_hybrid_search_no_backends_returns_empty(self) -> None:
        engine = HybridSearchEngine()
        results = await engine.search("anything")
        assert results == []

    async def test_search_vector_only_method(
        self, mock_vector_backend: AsyncMock, mock_fts_backend: AsyncMock
    ) -> None:
        engine = HybridSearchEngine(
            vector_backend=mock_vector_backend, fts_backend=mock_fts_backend
        )
        results = await engine.search_vector_only("test")

        assert all(r.source == "vector" for r in results)
        mock_fts_backend.search.assert_not_called()

    async def test_search_fts_only_method(
        self, mock_vector_backend: AsyncMock, mock_fts_backend: AsyncMock
    ) -> None:
        engine = HybridSearchEngine(
            vector_backend=mock_vector_backend, fts_backend=mock_fts_backend
        )
        results = await engine.search_fts_only("test")

        assert all(r.source == "fts" for r in results)
        mock_vector_backend.search.assert_not_called()

    async def test_rrf_scores_normalized(
        self, mock_vector_backend: AsyncMock, mock_fts_backend: AsyncMock
    ) -> None:
        engine = HybridSearchEngine(
            vector_backend=mock_vector_backend, fts_backend=mock_fts_backend
        )
        results = await engine.search("kubernetes")

        assert all(0.0 <= r.score <= 1.0 for r in results)
        # First result should have score 1.0 (max normalised)
        assert results[0].score == pytest.approx(1.0)

    async def test_limit_respected(
        self, mock_vector_backend: AsyncMock, mock_fts_backend: AsyncMock
    ) -> None:
        engine = HybridSearchEngine(
            vector_backend=mock_vector_backend, fts_backend=mock_fts_backend
        )
        results = await engine.search("kubernetes", limit=2)
        assert len(results) <= 2

    async def test_search_vector_only_no_backend(self) -> None:
        engine = HybridSearchEngine()
        results = await engine.search_vector_only("test")
        assert results == []

    async def test_search_fts_only_no_backend(self) -> None:
        engine = HybridSearchEngine()
        results = await engine.search_fts_only("test")
        assert results == []


class TestSimpleTextFTS:
    async def test_index_and_search(self) -> None:
        fts = SimpleTextFTS()
        fts.index("kubernetes cluster management", {"id": 1})
        fts.index("docker container runtime", {"id": 2})
        fts.index("kubernetes pod networking", {"id": 3})

        results = await fts.search("kubernetes")

        assert len(results) >= 2
        # Both kubernetes docs should rank higher than docker
        contents = [r[0] for r in results]
        assert "docker container runtime" not in contents[:2] or len(results) == 2

    async def test_search_empty_index(self) -> None:
        fts = SimpleTextFTS()
        results = await fts.search("anything")
        assert results == []

    async def test_search_empty_query(self) -> None:
        fts = SimpleTextFTS()
        fts.index("some document")
        results = await fts.search("")
        assert results == []

    async def test_scores_normalized_to_one(self) -> None:
        fts = SimpleTextFTS()
        fts.index("hello world hello")
        fts.index("hello there")

        results = await fts.search("hello")
        assert len(results) >= 1
        assert results[0][1] == pytest.approx(1.0)
        for _, score, _ in results:
            assert 0.0 <= score <= 1.0

    async def test_limit_respected(self) -> None:
        fts = SimpleTextFTS()
        for i in range(20):
            fts.index(f"document about topic {i}")

        results = await fts.search("document", limit=5)
        assert len(results) <= 5

    async def test_metadata_preserved(self) -> None:
        fts = SimpleTextFTS()
        fts.index("test document", {"source": "memory", "ts": 123})

        results = await fts.search("test")
        assert len(results) == 1
        assert results[0][2] == {"source": "memory", "ts": 123}
