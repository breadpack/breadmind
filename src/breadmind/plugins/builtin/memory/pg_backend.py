"""PostgreSQL backend for v2 Memory plugins.

Provides persistent storage for WorkingMemory, EpisodicMemory, and SemanticMemory.
asyncpg is an optional dependency — imported lazily.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class PgMemoryBackend:
    """asyncpg-based PostgreSQL backend for v2 memory plugins."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None  # asyncpg.Pool

    async def initialize(self) -> None:
        """Create connection pool and ensure tables exist."""
        try:
            import asyncpg
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PgMemoryBackend. "
                "Install it with: pip install asyncpg"
            ) from exc

        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        await self._create_tables()

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _create_tables(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS v2_working_memory (
                    session_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value JSONB NOT NULL,
                    expires_at TIMESTAMPTZ,
                    PRIMARY KEY (session_id, key)
                );

                CREATE TABLE IF NOT EXISTS v2_episodic_memory (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    keywords TEXT[] NOT NULL DEFAULT '{}',
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    importance FLOAT NOT NULL DEFAULT 0.5,
                    metadata JSONB NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_v2_episodic_session
                    ON v2_episodic_memory(session_id);

                CREATE TABLE IF NOT EXISTS v2_semantic_memory (
                    id SERIAL PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence FLOAT NOT NULL DEFAULT 1.0,
                    metadata JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(subject, predicate)
                );
            """)

    # ── Working Memory ───────────────────────────────────────────────

    async def working_get(self, session_id: str, key: str) -> Any | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT value FROM v2_working_memory
                WHERE session_id = $1 AND key = $2
                  AND (expires_at IS NULL OR expires_at > NOW())
                """,
                session_id, key,
            )
            if row is None:
                return None
            val = row["value"]
            return json.loads(val) if isinstance(val, str) else val

    async def working_put(
        self, session_id: str, key: str, value: Any, ttl: int | None = None,
    ) -> None:
        expires_at = None
        if ttl is not None:
            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO v2_working_memory (session_id, key, value, expires_at)
                VALUES ($1, $2, $3::jsonb, $4)
                ON CONFLICT (session_id, key) DO UPDATE SET
                    value = EXCLUDED.value,
                    expires_at = EXCLUDED.expires_at
                """,
                session_id, key, json.dumps(value, default=str), expires_at,
            )

    async def working_delete(self, session_id: str, key: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM v2_working_memory WHERE session_id = $1 AND key = $2",
                session_id, key,
            )

    async def working_get_session(self, session_id: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT key, value FROM v2_working_memory
                WHERE session_id = $1
                  AND (expires_at IS NULL OR expires_at > NOW())
                """,
                session_id,
            )
            result: dict[str, Any] = {}
            for row in rows:
                val = row["value"]
                result[row["key"]] = json.loads(val) if isinstance(val, str) else val
            return result

    async def working_clear_session(self, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM v2_working_memory WHERE session_id = $1",
                session_id,
            )

    # ── Episodic Memory ──────────────────────────────────────────────

    async def episodic_save(self, episode: dict) -> int:
        """Save an episode dict. Expected keys: id, content, keywords, timestamp, metadata."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO v2_episodic_memory
                    (content, keywords, timestamp, importance, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING id
                """,
                episode.get("content", ""),
                episode.get("keywords", []),
                episode.get("timestamp") or datetime.now(timezone.utc),
                episode.get("importance", 0.5),
                json.dumps(episode.get("metadata", {}), default=str),
            )
            return row["id"]

    async def episodic_search(
        self, keywords: list[str], limit: int = 10,
    ) -> list[dict]:
        """Search episodes by keyword overlap or content match."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *, (
                    SELECT COUNT(*) FROM unnest(keywords) kw
                    WHERE kw = ANY($1::TEXT[])
                ) AS score
                FROM v2_episodic_memory
                WHERE keywords && $1::TEXT[]
                ORDER BY score DESC, timestamp DESC
                LIMIT $2
                """,
                keywords, limit,
            )
            return [self._row_to_episode(r) for r in rows]

    async def episodic_search_by_content(
        self, query: str, limit: int = 10,
    ) -> list[dict]:
        """Full-text search on content field."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM v2_episodic_memory
                WHERE content ILIKE '%' || $1 || '%'
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                query, limit,
            )
            return [self._row_to_episode(r) for r in rows]

    async def episodic_count(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM v2_episodic_memory")

    async def episodic_get_recent(self, limit: int = 10) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM v2_episodic_memory ORDER BY timestamp DESC LIMIT $1",
                limit,
            )
            return [self._row_to_episode(r) for r in rows]

    async def episodic_delete_oldest(self, count: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM v2_episodic_memory
                WHERE id IN (
                    SELECT id FROM v2_episodic_memory
                    ORDER BY timestamp ASC
                    LIMIT $1
                )
                """,
                count,
            )

    @staticmethod
    def _row_to_episode(row) -> dict:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return {
            "id": str(row["id"]),
            "content": row["content"],
            "keywords": list(row["keywords"]) if row["keywords"] else [],
            "timestamp": row["timestamp"].isoformat() if row["timestamp"] else "",
            "importance": row["importance"],
            "metadata": metadata or {},
        }

    # ── Semantic Memory ──────────────────────────────────────────────

    async def semantic_upsert(
        self, subject: str, predicate: str, obj: str,
        confidence: float = 1.0, metadata: dict | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO v2_semantic_memory (subject, predicate, object, confidence, metadata, updated_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
                ON CONFLICT (subject, predicate) DO UPDATE SET
                    object = EXCLUDED.object,
                    confidence = EXCLUDED.confidence,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                subject, predicate, obj, confidence,
                json.dumps(metadata or {}, default=str),
            )

    async def semantic_query(self, term: str, limit: int = 10) -> list[dict]:
        """Query triples where the term appears as subject or object."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM v2_semantic_memory
                WHERE LOWER(subject) = LOWER($1) OR LOWER(object) = LOWER($1)
                ORDER BY confidence DESC, updated_at DESC
                LIMIT $2
                """,
                term, limit,
            )
            return [self._row_to_triple(r) for r in rows]

    async def semantic_query_many(
        self, terms: list[str], limit: int = 10,
    ) -> list[dict]:
        """Query triples where any of the terms appear as subject or object."""
        terms_lower = [t.lower() for t in terms]
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM v2_semantic_memory
                WHERE LOWER(subject) = ANY($1::TEXT[]) OR LOWER(object) = ANY($1::TEXT[])
                ORDER BY confidence DESC, updated_at DESC
                LIMIT $2
                """,
                terms_lower, limit,
            )
            return [self._row_to_triple(r) for r in rows]

    async def semantic_delete(self, subject: str, predicate: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM v2_semantic_memory WHERE subject = $1 AND predicate = $2",
                subject, predicate,
            )

    async def semantic_count(self) -> int:
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM v2_semantic_memory")

    @staticmethod
    def _row_to_triple(row) -> dict:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return {
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "confidence": row["confidence"],
            "metadata": metadata or {},
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
        }
