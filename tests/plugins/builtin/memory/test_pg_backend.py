"""Tests for PgMemoryBackend and backend integration with memory classes.

All tests mock asyncpg so no real database is needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.core.protocols import Episode, KGTriple, Message
from breadmind.plugins.builtin.memory.pg_backend import PgMemoryBackend


# ── Helpers ──────────────────────────────────────────────────────────


def _make_pool_mock():
    """Create a mock asyncpg pool with acquire() context manager."""
    pool = MagicMock()
    conn = AsyncMock()

    # Make pool.acquire() return an async context manager yielding conn
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm
    pool.close = AsyncMock()

    return pool, conn


# ── PgMemoryBackend unit tests ───────────────────────────────────────


class TestPgBackendInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_pool_and_tables(self):
        backend = PgMemoryBackend(dsn="postgresql://test:test@localhost/test")
        pool_mock, conn_mock = _make_pool_mock()

        with patch(
            "breadmind.plugins.builtin.memory.pg_backend.PgMemoryBackend._create_tables",
            new_callable=AsyncMock,
        ) as mock_tables:
            with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=pool_mock):
                await backend.initialize()
                mock_tables.assert_awaited_once()
                assert backend._pool is pool_mock

    @pytest.mark.asyncio
    async def test_close(self):
        backend = PgMemoryBackend(dsn="postgresql://test:test@localhost/test")
        pool_mock = AsyncMock()
        backend._pool = pool_mock
        await backend.close()
        pool_mock.close.assert_awaited_once()
        assert backend._pool is None


class TestPgBackendWorking:
    @pytest.mark.asyncio
    async def test_working_put_and_get(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool

        # Test put
        await backend.working_put("s1", "messages", [{"role": "user", "content": "hi"}])
        conn.execute.assert_awaited_once()
        call_args = conn.execute.call_args
        assert "INSERT INTO v2_working_memory" in call_args[0][0]
        assert call_args[0][1] == "s1"
        assert call_args[0][2] == "messages"

    @pytest.mark.asyncio
    async def test_working_get_returns_none_when_missing(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetchrow.return_value = None

        result = await backend.working_get("s1", "messages")
        assert result is None

    @pytest.mark.asyncio
    async def test_working_get_returns_parsed_value(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetchrow.return_value = {"value": [{"role": "user", "content": "hi"}]}

        result = await backend.working_get("s1", "messages")
        assert result == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_working_delete(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool

        await backend.working_delete("s1", "messages")
        conn.execute.assert_awaited_once()
        assert "DELETE FROM v2_working_memory" in conn.execute.call_args[0][0]

    @pytest.mark.asyncio
    async def test_working_get_session(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetch.return_value = [
            {"key": "messages", "value": [{"role": "user", "content": "hi"}]},
            {"key": "context", "value": {"tool": "shell"}},
        ]

        result = await backend.working_get_session("s1")
        assert "messages" in result
        assert "context" in result

    @pytest.mark.asyncio
    async def test_working_put_with_ttl(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool

        await backend.working_put("s1", "temp", "value", ttl=60)
        call_args = conn.execute.call_args
        # expires_at should not be None when ttl is set
        assert call_args[0][4] is not None


class TestPgBackendEpisodic:
    @pytest.mark.asyncio
    async def test_episodic_save(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetchrow.return_value = {"id": 1}

        episode = {
            "content": "K8s pod crashed",
            "keywords": ["k8s", "pod"],
            "timestamp": datetime.now(timezone.utc),
            "metadata": {},
        }
        result = await backend.episodic_save(episode)
        assert result == 1
        assert "INSERT INTO v2_episodic_memory" in conn.fetchrow.call_args[0][0]

    @pytest.mark.asyncio
    async def test_episodic_search(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetch.return_value = [
            {
                "id": 1, "content": "K8s pod crashed",
                "keywords": ["k8s", "pod"], "timestamp": datetime.now(timezone.utc),
                "importance": 0.8, "metadata": "{}",
                "score": 2,
            }
        ]

        results = await backend.episodic_search(["k8s", "pod"], limit=5)
        assert len(results) == 1
        assert results[0]["content"] == "K8s pod crashed"
        assert "keywords && $1" in conn.fetch.call_args[0][0]

    @pytest.mark.asyncio
    async def test_episodic_count(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetchval.return_value = 42

        count = await backend.episodic_count()
        assert count == 42

    @pytest.mark.asyncio
    async def test_episodic_delete_oldest(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool

        await backend.episodic_delete_oldest(5)
        assert "DELETE FROM v2_episodic_memory" in conn.execute.call_args[0][0]
        assert "ORDER BY timestamp ASC" in conn.execute.call_args[0][0]


class TestPgBackendSemantic:
    @pytest.mark.asyncio
    async def test_semantic_upsert(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool

        await backend.semantic_upsert("pod-nginx", "runs_on", "node-1", confidence=0.9)
        call_sql = conn.execute.call_args[0][0]
        assert "INSERT INTO v2_semantic_memory" in call_sql
        assert "ON CONFLICT (subject, predicate)" in call_sql

    @pytest.mark.asyncio
    async def test_semantic_query(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetch.return_value = [
            {
                "subject": "pod-nginx", "predicate": "runs_on", "object": "node-1",
                "confidence": 0.9, "metadata": "{}", "updated_at": datetime.now(timezone.utc),
            }
        ]

        results = await backend.semantic_query("pod-nginx", limit=5)
        assert len(results) == 1
        assert results[0]["subject"] == "pod-nginx"

    @pytest.mark.asyncio
    async def test_semantic_query_many(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        conn.fetch.return_value = [
            {
                "subject": "pod-a", "predicate": "runs_on", "object": "node-1",
                "confidence": 1.0, "metadata": {}, "updated_at": datetime.now(timezone.utc),
            },
            {
                "subject": "pod-b", "predicate": "runs_on", "object": "node-1",
                "confidence": 1.0, "metadata": {}, "updated_at": datetime.now(timezone.utc),
            },
        ]

        results = await backend.semantic_query_many(["node-1"], limit=10)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_semantic_delete(self):
        backend = PgMemoryBackend(dsn="postgresql://x")
        pool, conn = _make_pool_mock()
        backend._pool = pool

        await backend.semantic_delete("pod-nginx", "runs_on")
        assert "DELETE FROM v2_semantic_memory" in conn.execute.call_args[0][0]


# ── Integration: Memory classes with backend ─────────────────────────


class TestWorkingMemoryWithBackend:
    @pytest.mark.asyncio
    async def test_put_delegates_to_backend(self):
        backend = AsyncMock()
        backend.working_put = AsyncMock()
        backend.working_get = AsyncMock(return_value=None)

        from breadmind.plugins.builtin.memory.working_memory import WorkingMemory
        wm = WorkingMemory(backend=backend)
        msgs = [Message(role="user", content="hello")]
        await wm.working_put("s1", msgs)
        backend.working_put.assert_awaited_once()
        call_args = backend.working_put.call_args
        assert call_args[0][0] == "s1"
        assert call_args[0][1] == "messages"

    @pytest.mark.asyncio
    async def test_get_delegates_to_backend(self):
        backend = AsyncMock()
        backend.working_get = AsyncMock(
            return_value=[{"role": "user", "content": "hello"}]
        )

        from breadmind.plugins.builtin.memory.working_memory import WorkingMemory
        wm = WorkingMemory(backend=backend)
        result = await wm.working_get("s1")
        assert len(result) == 1
        assert result[0].role == "user"
        assert result[0].content == "hello"

    @pytest.mark.asyncio
    async def test_get_returns_empty_when_backend_none_value(self):
        backend = AsyncMock()
        backend.working_get = AsyncMock(return_value=None)

        from breadmind.plugins.builtin.memory.working_memory import WorkingMemory
        wm = WorkingMemory(backend=backend)
        result = await wm.working_get("nonexistent")
        assert result == []


class TestEpisodicMemoryWithBackend:
    @pytest.mark.asyncio
    async def test_save_delegates_to_backend(self):
        backend = AsyncMock()
        backend.episodic_save = AsyncMock(return_value=1)
        backend.episodic_count = AsyncMock(return_value=1)

        from breadmind.plugins.builtin.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(backend=backend)
        await mem.episodic_save(
            Episode(id="e1", content="test", keywords=["k8s"])
        )
        backend.episodic_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_delegates_to_backend(self):
        backend = AsyncMock()
        backend.episodic_search = AsyncMock(return_value=[
            {"id": "1", "content": "K8s crash", "keywords": ["k8s"], "timestamp": "", "metadata": {}}
        ])

        from breadmind.plugins.builtin.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(backend=backend)
        results = await mem.episodic_search("k8s crash")
        assert len(results) == 1
        assert isinstance(results[0], Episode)

    @pytest.mark.asyncio
    async def test_search_wildcard_delegates_to_backend(self):
        backend = AsyncMock()
        backend.episodic_get_recent = AsyncMock(return_value=[
            {"id": "1", "content": "A", "keywords": [], "timestamp": "", "metadata": {}}
        ])

        from breadmind.plugins.builtin.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(backend=backend)
        results = await mem.episodic_search("*", limit=10)
        backend.episodic_get_recent.assert_awaited_once_with(10)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_count_async_with_backend(self):
        backend = AsyncMock()
        backend.episodic_count = AsyncMock(return_value=42)

        from breadmind.plugins.builtin.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(backend=backend)
        assert await mem.count_async() == 42


class TestSemanticMemoryWithBackend:
    @pytest.mark.asyncio
    async def test_upsert_delegates_to_backend(self):
        backend = AsyncMock()
        backend.semantic_upsert = AsyncMock()

        from breadmind.plugins.builtin.memory.semantic_memory import SemanticMemory
        mem = SemanticMemory(backend=backend)
        await mem.semantic_upsert([
            KGTriple(subject="pod-nginx", predicate="runs_on", object="node-1"),
        ])
        backend.semantic_upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_delegates_to_backend(self):
        backend = AsyncMock()
        backend.semantic_query_many = AsyncMock(return_value=[
            {"subject": "pod-nginx", "predicate": "runs_on", "object": "node-1", "metadata": {}}
        ])

        from breadmind.plugins.builtin.memory.semantic_memory import SemanticMemory
        mem = SemanticMemory(backend=backend)
        results = await mem.semantic_query(["pod-nginx"])
        assert len(results) == 1
        assert isinstance(results[0], KGTriple)

    @pytest.mark.asyncio
    async def test_count_async_with_backend(self):
        backend = AsyncMock()
        backend.semantic_count = AsyncMock(return_value=10)

        from breadmind.plugins.builtin.memory.semantic_memory import SemanticMemory
        mem = SemanticMemory(backend=backend)
        assert await mem.count_async() == 10


# ── Backward compatibility: in-memory without backend ────────────────


class TestInMemoryBackwardCompat:
    """Ensure existing in-memory behavior is preserved when backend=None."""

    @pytest.mark.asyncio
    async def test_working_memory_in_memory(self):
        from breadmind.plugins.builtin.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        msgs = [Message(role="user", content="hello")]
        await wm.working_put("s1", msgs)
        result = await wm.working_get("s1")
        assert len(result) == 1
        assert result[0].content == "hello"

    @pytest.mark.asyncio
    async def test_episodic_memory_in_memory(self):
        from breadmind.plugins.builtin.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory()
        await mem.episodic_save(Episode(id="e1", content="test", keywords=["k8s"]))
        assert mem.count() == 1
        results = await mem.episodic_search("k8s")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_semantic_memory_in_memory(self):
        from breadmind.plugins.builtin.memory.semantic_memory import SemanticMemory
        mem = SemanticMemory()
        await mem.semantic_upsert([
            KGTriple(subject="pod-a", predicate="runs_on", object="node-1"),
        ])
        assert mem.count() == 1
        results = await mem.semantic_query(["pod-a"])
        assert len(results) == 1
