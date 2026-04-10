"""Fixtures for storage-layer integration tests.

Provides a ``test_db`` fixture that connects to a real PostgreSQL
database (required because migrations use PG-specific features like
JSONB, UUID, BIGSERIAL, TIMESTAMPTZ, pgcrypto).

The fixture looks for a DSN in the following environment variables
(in order of priority):

    TEST_DATABASE_URL
    DATABASE_URL

If neither is set, it falls back to the local ``docker compose``
postgres service defaults (see ``docker-compose.yaml``):

    postgresql://breadmind:breadmind_dev@localhost:5434/breadmind

Tests are skipped gracefully if no database is reachable.
"""
from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
import pytest_asyncio

from breadmind.storage.database import Database
from breadmind.storage.migrator import MigrationConfig, Migrator


def _default_dsn() -> str:
    return (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://breadmind:breadmind_dev@localhost:5434/breadmind"
    )


@pytest_asyncio.fixture
async def test_db() -> AsyncIterator[Database]:
    """Yield a connected ``Database`` with migrations applied to head.

    Skips the test if PostgreSQL is not reachable.
    """
    import asyncpg

    dsn = _default_dsn()

    # Probe reachability before running migrations so we can skip cleanly.
    try:
        probe = await asyncpg.connect(dsn, timeout=3)
        await probe.close()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable at {dsn}: {exc}")

    # Run alembic migrations up to head so the schema under test exists.
    migrator = Migrator(MigrationConfig(database_url=dsn))
    migrator.upgrade("head")

    db = Database(dsn)
    # Create a raw pool without re-running legacy _migrate() side effects
    # by setting up the pool manually (mirrors Database.connect()).
    db._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        yield db
    finally:
        await db.disconnect()
