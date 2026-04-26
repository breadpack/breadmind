"""Shared test fixtures for BreadMind tests.

Factory functions live in ``tests.factories`` and are re-exported here so
that both fixtures and test files can use them.
"""
from __future__ import annotations

import os
import uuid as _uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from breadmind.core.protocols import AgentContext
from breadmind.storage.database import Database
from breadmind.storage.migrator import MigrationConfig, Migrator

# Re-export factory functions so they are discoverable from conftest
from tests.factories import (  # noqa: F401
    make_agent_context,
    make_mock_prompt_builder,
    make_mock_provider,
    make_mock_tool_registry,
    make_text_response,
    make_tool_call_response,
    make_tool_result,
)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def safety_config():
    """Legacy safety config dict (kept for backward compatibility)."""
    return {
        "blacklist": {
            "test": ["dangerous_action"],
        },
        "require_approval": ["needs_approval"],
    }


@pytest.fixture
def mock_provider() -> AsyncMock:
    """Provider that returns a single default text response."""
    return make_mock_provider()


@pytest.fixture
def mock_prompt_builder() -> MagicMock:
    """Prompt builder that returns a single identity block."""
    return make_mock_prompt_builder()


@pytest.fixture
def mock_tool_registry() -> MagicMock:
    """Tool registry with empty schemas."""
    return make_mock_tool_registry()


@pytest.fixture
def agent_context() -> AgentContext:
    """Default AgentContext for tests."""
    return make_agent_context()


@pytest.fixture
def safety_guard():
    """SafetyGuard in fully autonomous mode."""
    from breadmind.plugins.builtin.safety.guard import SafetyGuard
    return SafetyGuard(autonomy="auto")


# ---------------------------------------------------------------------------
# Database fixture (shared across integration test suites)
# ---------------------------------------------------------------------------


def _default_test_dsn() -> str:
    return (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://breadmind:breadmind_dev@localhost:5434/breadmind"
    )


@pytest_asyncio.fixture
async def test_db() -> AsyncIterator[Database]:
    """Yield a connected ``Database`` with migrations applied to head.

    Skips the test if PostgreSQL is not reachable. Shared fixture so
    that any test directory (storage, flow, etc.) can use it without
    duplicating the setup logic.
    """
    import asyncpg

    dsn = _default_test_dsn()

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


@pytest_asyncio.fixture
async def insert_org(test_db):
    """Return an async callable that inserts a minimal org_projects row.

    Usage::

        async def test_foo(insert_org):
            org_id = uuid.uuid4()
            await insert_org(org_id)
    """
    async def _insert(org_id: _uuid.UUID) -> None:
        async with test_db.acquire() as conn:
            await conn.execute(
                "INSERT INTO org_projects (id, name, slack_team_id) VALUES ($1, $2, $3) "
                "ON CONFLICT (id) DO NOTHING",
                org_id, f"test-org-{org_id}", f"T{str(org_id)[:8]}",
            )
    return _insert


@pytest.fixture
def message_loop_agent(
    mock_provider,
    mock_prompt_builder,
    mock_tool_registry,
    safety_guard,
):
    """MessageLoopAgent wired with default mock collaborators."""
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
    return MessageLoopAgent(
        provider=mock_provider,
        prompt_builder=mock_prompt_builder,
        tool_registry=mock_tool_registry,
        safety_guard=safety_guard,
        max_turns=5,
    )
