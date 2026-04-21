"""Shared fixtures for KB test suite."""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import asyncpg
import fakeredis.aioredis
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from breadmind.storage.database import Database


# ---------------------------------------------------------------------------
# P1 fixtures — kept intact
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_vocab() -> list[str]:
    return ["Acme Corp", "Globex", "Initech"]


@pytest_asyncio.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# P2 fixtures — Postgres container + seeded KB rows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("pgvector/pgvector:pg17") as pg:
        yield pg


@pytest_asyncio.fixture
async def db(pg_container) -> Database:
    raw_url = pg_container.get_connection_url()
    # testcontainers returns a SQLAlchemy-style URL; asyncpg needs plain postgresql://
    dsn = raw_url.replace("postgresql+psycopg2://", "postgresql://")
    os.environ["DATABASE_URL"] = dsn

    database = Database(dsn)
    database._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)

    async with database.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS org_projects (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                slack_team_id TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS org_project_members (
                project_id UUID REFERENCES org_projects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (project_id, user_id)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS org_channel_map (
                channel_id TEXT PRIMARY KEY,
                project_id UUID REFERENCES org_projects(id),
                visibility TEXT NOT NULL
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS org_knowledge (
                id BIGSERIAL PRIMARY KEY,
                project_id UUID REFERENCES org_projects(id),
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT NOT NULL,
                source_channel TEXT,
                tags TEXT[] DEFAULT '{}',
                embedding vector(384),
                tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', title || ' ' || body)) STORED,
                promoted_from TEXT,
                promoted_by TEXT,
                promoted_at TIMESTAMPTZ,
                revision INT NOT NULL DEFAULT 1,
                superseded_by BIGINT REFERENCES org_knowledge(id),
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_org_kn_tsv ON org_knowledge USING gin(tsv);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_org_kn_embedding ON org_knowledge "
            "USING hnsw (embedding vector_cosine_ops);"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_sources (
                id BIGSERIAL PRIMARY KEY,
                knowledge_id BIGINT REFERENCES org_knowledge(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                source_ref TEXT,
                captured_at TIMESTAMPTZ DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_audit_log (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT now(),
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                subject_type TEXT,
                subject_id TEXT,
                project_id UUID,
                metadata JSONB
            );
        """)

    yield database

    async with database.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS kb_sources CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS org_knowledge CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS org_channel_map CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS org_project_members CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS org_projects CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS kb_audit_log CASCADE;")

    await database._pool.close()


@pytest_asyncio.fixture
async def seeded_project(db) -> UUID:
    pid = uuid4()
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO org_projects(id, name, slack_team_id) VALUES ($1,$2,$3)",
            pid, "payments", "T0001",
        )
        await conn.execute(
            "INSERT INTO org_project_members(project_id, user_id, role) VALUES ($1,$2,$3)",
            pid, "U_ALICE", "member",
        )
    return pid


@pytest_asyncio.fixture
async def seeded_kb(db, seeded_project) -> list[int]:
    """3 rows: leak-fix (channel_members_only), payments-howto (public), archived."""
    pid = seeded_project
    vec_a = "[" + ",".join(["0.1"] * 384) + "]"
    vec_b = "[" + ",".join(["0.2"] * 384) + "]"
    vec_c = "[" + ",".join(["0.3"] * 384) + "]"
    async with db.acquire() as conn:
        row_a = await conn.fetchval(
            "INSERT INTO org_knowledge(project_id, title, body, category, "
            "source_channel, embedding) VALUES ($1,$2,$3,$4,$5,$6::vector) RETURNING id",
            pid, "Payment memory leak fix",
            "Cache eviction was never called; fixed in CL 12345.",
            "bug_fix", "C_PRIV", vec_a,
        )
        row_b = await conn.fetchval(
            "INSERT INTO org_knowledge(project_id, title, body, category, "
            "source_channel, embedding) VALUES ($1,$2,$3,$4,$5,$6::vector) RETURNING id",
            pid, "Payments module howto",
            "Run `make payments` to boot a local sandbox.",
            "howto", None, vec_b,
        )
        row_c = await conn.fetchval(
            "INSERT INTO org_knowledge(project_id, title, body, category, "
            "source_channel, embedding) VALUES ($1,$2,$3,$4,$5,$6::vector) RETURNING id",
            pid, "Archived onboarding",
            "Old onboarding doc superseded by the new one.",
            "onboarding", None, vec_c,
        )
        await conn.execute(
            "INSERT INTO kb_sources(knowledge_id, source_type, source_uri, source_ref) "
            "VALUES ($1,$2,$3,$4)",
            row_a, "slack_msg", "https://slack.com/archives/C_PRIV/p12345", "ts=12345",
        )
        await conn.execute(
            "INSERT INTO kb_sources(knowledge_id, source_type, source_uri, source_ref) "
            "VALUES ($1,$2,$3,$4)",
            row_b, "confluence", "https://wiki/payments/howto", None,
        )
    return [row_a, row_b, row_c]


# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


class FakeEmbedder:
    """Deterministic embedder for tests: returns a 384-dim vector derived from query hash."""

    dimensions = 384

    async def encode(self, text: str) -> list[float]:
        # map to the same vec_a-ish if 'leak' keyword present, else vec_b-ish
        base = 0.1 if "leak" in text.lower() else 0.2
        return [base] * 384


@pytest.fixture
def embedder():
    return FakeEmbedder()


class FakeACL:
    def __init__(
        self,
        allowed_channels: set[str] | None = None,
        user_projects_map: dict[str, list[UUID]] | None = None,
    ):
        self._allowed = allowed_channels or set()
        self._projects = user_projects_map or {}

    async def user_projects(self, user_id: str) -> list[UUID]:
        return self._projects.get(user_id, [])

    async def filter_knowledge(
        self,
        user_id: str,
        project_id: UUID,
        candidate_ids: list[int],
    ) -> list[int]:
        # In the default fake, drop rows whose source_channel is private
        # and user is not a member of that channel. The retriever already
        # SQL-filtered the rest, so this fake just passes them through.
        return candidate_ids

    async def can_read_channel(self, user_id: str, channel_id: str) -> bool:
        return channel_id in self._allowed


@pytest.fixture
def acl(seeded_project):
    return FakeACL(
        allowed_channels=set(),  # Alice cannot read C_PRIV by default
        user_projects_map={"U_ALICE": [seeded_project]},
    )
