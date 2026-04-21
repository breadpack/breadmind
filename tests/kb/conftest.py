"""Shared fixtures for KB test suite."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
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
    _prev_db_url = os.environ.get("DATABASE_URL")
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
        # promotion_candidates — mirrors migration 004_org_kb, plus
        # sensitive_flag column added in 005_kb_p3_feedback.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promotion_candidates (
                id                  BIGSERIAL PRIMARY KEY,
                project_id          UUID REFERENCES org_projects(id),
                extracted_from      TEXT NOT NULL,
                original_user       TEXT,
                proposed_title      TEXT,
                proposed_body       TEXT,
                proposed_category   TEXT,
                sources_json        JSONB,
                confidence          REAL,
                status              TEXT NOT NULL DEFAULT 'pending',
                reviewer            TEXT,
                reviewed_at         TIMESTAMPTZ,
                created_at          TIMESTAMPTZ DEFAULT now(),
                sensitive_flag      BOOLEAN NOT NULL DEFAULT FALSE
            );
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_promo_project_status "
            "ON promotion_candidates(project_id, status);"
        )

    try:
        yield database
    finally:
        if _prev_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev_db_url

    async with database.acquire() as conn:
        # Drop promotion_candidates before org_projects to avoid FK violation.
        await conn.execute("DROP TABLE IF EXISTS promotion_candidates CASCADE;")
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
        # Additional membership rows used by downstream P3 tests. U-LEAD / U-MEMBER
        # are distinct from U_ALICE (note the hyphen vs underscore).
        await conn.execute(
            "INSERT INTO org_project_members(project_id, user_id, role) VALUES ($1,$2,$3)",
            pid, "U-LEAD", "lead",
        )
        await conn.execute(
            "INSERT INTO org_project_members(project_id, user_id, role) VALUES ($1,$2,$3)",
            pid, "U-MEMBER", "member",
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
        # Pass-through: returns all candidate IDs unchanged. The real ACL would
        # filter by channel membership; retriever SQL handles the bulk ACL
        # pre-filter, and this defensive second pass is a no-op in tests.
        return candidate_ids

    async def can_read_channel(self, user_id: str, channel_id: str) -> bool:
        return channel_id in self._allowed


@pytest.fixture
def acl(seeded_project):
    return FakeACL(
        allowed_channels=set(),  # Alice cannot read C_PRIV by default
        user_projects_map={"U_ALICE": [seeded_project]},
    )


# ---------------------------------------------------------------------------
# P3 fakes — LLM router, sensitive classifier, Slack web client
# ---------------------------------------------------------------------------


@dataclass
class FakeLLMRouter:
    """Scripted LLM: ``script`` is a list of responses returned in order.

    Exhausting the script without seeding more raises AssertionError so tests
    that forgot to seed a response fail loudly rather than passing on a
    coincidentally-parseable ``"{}"`` fallback.
    """

    script: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        """Record the call and return the next scripted response.

        Raises AssertionError if the script is exhausted.
        """
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.script:
            raise AssertionError(
                "FakeLLMRouter.script exhausted; test did not seed a response. "
                "Seed expected responses via `fake_llm_router.script = [...]`."
            )
        return self.script.pop(0)


@pytest.fixture
def fake_llm_router() -> FakeLLMRouter:
    return FakeLLMRouter()


@dataclass
class FakeSensitiveClassifier:
    """Substring-based sensitive-content classifier for deterministic tests."""

    deny_substrings: list[str] = field(default_factory=list)

    async def is_sensitive(self, text: str) -> bool:
        return any(s in text for s in self.deny_substrings)


@pytest.fixture
def fake_sensitive() -> FakeSensitiveClassifier:
    return FakeSensitiveClassifier()


@dataclass
class FakeSlackClient:
    """Mimic of ``slack_sdk.web.async_client.AsyncWebClient`` for pipeline tests.

    Records DM posts and opened views so tests can assert on side effects.
    ``members_by_channel`` is pre-populated by individual tests to control the
    return of ``conversations_members``.
    """

    dms: list[dict] = field(default_factory=list)
    views_opened: list[dict] = field(default_factory=list)
    members_by_channel: dict[str, list[str]] = field(default_factory=dict)
    # Optional test-overridable hooks (downstream tasks may monkey-patch these).
    conversations_replies_return: list = field(default_factory=list)

    async def chat_postMessage(self, **kwargs: Any) -> dict:
        self.dms.append(kwargs)
        return {"ok": True, "ts": "1.0"}

    async def conversations_open(self, users: str, **kwargs: Any) -> dict:
        return {"ok": True, "channel": {"id": f"D-{users}"}}

    async def views_open(self, trigger_id: str, view: dict) -> dict:
        self.views_opened.append({"trigger_id": trigger_id, "view": view})
        return {"ok": True}

    async def conversations_members(self, channel: str, **kwargs: Any) -> dict:
        return {"ok": True, "members": self.members_by_channel.get(channel, [])}


@pytest.fixture
def fake_slack_client() -> FakeSlackClient:
    return FakeSlackClient()


# ---------------------------------------------------------------------------
# Aliases — pasted plan code may reference ``pg_db`` instead of ``db``.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pg_db(db):
    """Alias for ``db`` so plan snippets using ``pg_db`` run as-is.

    Mirrors the async-generator shape of the ``db`` fixture; yielding the same
    Database instance means teardown remains owned by ``db``.
    """
    yield db
