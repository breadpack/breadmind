"""E2E harness: Postgres via testcontainers + fakeredis + stubs."""
from __future__ import annotations

import asyncpg
import fakeredis.aioredis
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("pgvector/pgvector:pg17") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_dsn(pg_container) -> str:
    raw = pg_container.get_connection_url()
    return raw.replace("postgresql+psycopg2", "postgresql")


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(pg_dsn):
    # This project keeps Alembic config programmatic (no repo-root alembic.ini).
    # Use the project's Migrator wrapper which points at
    # src/breadmind/storage/migrations.
    from breadmind.storage.migrator import MigrationConfig, Migrator

    migrator = Migrator(MigrationConfig(database_url=pg_dsn))
    migrator.upgrade("head")


@pytest.fixture(scope="session", autouse=True)
def _seed(pg_dsn, _apply_migrations):
    import subprocess
    subprocess.check_call(
        ["python", "scripts/seed_pilot_data.py", "--dsn", pg_dsn]
    )


@pytest.fixture
async def db(pg_dsn):
    conn = await asyncpg.connect(dsn=pg_dsn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    try:
        yield r
    finally:
        await r.aclose()


@pytest.fixture
def slack():
    from tests.e2e.fixtures.slack import FakeSlackClient
    return FakeSlackClient()


@pytest.fixture
def llm():
    from tests.e2e.fixtures.llm import StubLLM
    return StubLLM()


@pytest.fixture(autouse=True)
def _reset_metrics():
    from prometheus_client import CollectorRegistry

    from breadmind.kb import metrics
    metrics._build_metrics(CollectorRegistry())
