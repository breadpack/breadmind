"""Tests for migration 010 — KB backfill schema.

Adds provenance columns + indexes to ``org_knowledge`` and creates the
``kb_backfill_jobs`` and ``kb_backfill_org_budget`` tables. The shared
``test_db`` fixture (from ``tests/conftest.py``) connects to a live
Postgres instance and upgrades to head before yielding, so by the time
these assertions run the 010 migration has already been applied.
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

from breadmind.storage.migrator import MigrationConfig, Migrator


_NEW_ORG_KNOWLEDGE_COLS = {
    "source_kind",
    "source_native_id",
    "source_created_at",
    "source_updated_at",
    "parent_ref",
}


async def test_010_upgrade_adds_org_knowledge_columns(test_db):
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'org_knowledge'
            """
        )
        present = {r["column_name"] for r in rows}
        missing = _NEW_ORG_KNOWLEDGE_COLS - present
        assert not missing, f"missing org_knowledge columns: {missing}"


async def test_010_creates_unique_partial_index(test_db, insert_org):
    org_id = uuid.uuid4()
    await insert_org(org_id)

    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO org_knowledge "
            "(project_id, title, body, category, source_kind, source_native_id) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            org_id, "t1", "b1", "howto", "slack_msg", "C1:1.0",
        )
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            await conn.execute(
                "INSERT INTO org_knowledge "
                "(project_id, title, body, category, source_kind, source_native_id) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                org_id, "t2", "b2", "howto", "slack_msg", "C1:1.0",
            )


async def test_010_creates_kb_backfill_jobs(test_db):
    expected = {
        "id", "org_id", "source_kind", "source_filter", "instance_id",
        "since_ts", "until_ts", "dry_run", "token_budget", "status",
        "last_cursor", "progress_json", "skipped_json", "started_at",
        "finished_at", "error", "created_by", "created_at",
    }
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'kb_backfill_jobs'
            """
        )
        present = {r["column_name"] for r in rows}
        missing = expected - present
        assert not missing, f"missing kb_backfill_jobs columns: {missing}"

        idx = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'kb_backfill_jobs'"
        )
        names = {r["indexname"] for r in idx}
        assert "ix_kb_backfill_org_status" in names


async def test_010_creates_kb_backfill_org_budget(test_db):
    expected = {"org_id", "period_month", "tokens_used", "tokens_ceiling", "updated_at"}
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'kb_backfill_org_budget'
            """
        )
        present = {r["column_name"] for r in rows}
        missing = expected - present
        assert not missing, f"missing kb_backfill_org_budget columns: {missing}"


async def test_010_downgrade_drops_everything(test_db):
    """Round-trip: downgrade to 009_episodic_org_id, assert schema reverted,
    then upgrade back to head so subsequent tests are unaffected.
    """
    import os

    dsn = (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://breadmind:breadmind_dev@localhost:5434/breadmind"
    )

    migrator = Migrator(MigrationConfig(database_url=dsn))

    try:
        migrator.downgrade("009_episodic_org_id")

        probe = await asyncpg.connect(dsn, timeout=3)
        try:
            col_rows = await probe.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'org_knowledge'
                """
            )
            present = {r["column_name"] for r in col_rows}
            leaked = _NEW_ORG_KNOWLEDGE_COLS & present
            assert not leaked, f"org_knowledge columns still present after downgrade: {leaked}"

            tbls = await probe.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name IN ('kb_backfill_jobs', 'kb_backfill_org_budget')
                """
            )
            assert tbls == [], "backfill tables still present after downgrade"

            idx_rows = await probe.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'org_knowledge'"
            )
            idx = {r["indexname"] for r in idx_rows}
            for name in (
                "uq_org_knowledge_source_native",
                "ix_org_knowledge_source_created_at",
                "ix_org_knowledge_source_updated_at",
                "ix_org_knowledge_parent_ref",
            ):
                assert name not in idx, f"{name} still present after downgrade"
        finally:
            await probe.close()
    finally:
        migrator.upgrade("head")
