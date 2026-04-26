"""Tests for migration 009 — episodic org_id UUID FK + composite indexes.

The ``test_db`` fixture (from ``tests/conftest.py``) connects to a live
Postgres instance and upgrades to head before yielding, so by the time
these assertions run the 009 migration has already been applied.
"""
from __future__ import annotations

from breadmind.storage.migrator import MigrationConfig, Migrator


async def test_009_upgrade_adds_org_id_column(test_db):
    async with test_db.acquire() as conn:
        # Check column exists with correct type (uuid) and is nullable
        col_rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'episodic_notes'
              AND column_name = 'org_id'
            """
        )
        assert len(col_rows) == 1, "org_id column not found on episodic_notes"
        col = col_rows[0]
        assert col["data_type"] == "uuid", f"expected uuid, got {col['data_type']}"
        assert col["is_nullable"] == "YES", "org_id should be nullable"

        # Check FK to org_projects(id) with ON DELETE SET NULL
        fk_rows = await conn.fetch(
            """
            SELECT
                kcu.column_name,
                ccu.table_name  AS foreign_table,
                ccu.column_name AS foreign_column,
                rc.delete_rule
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.referential_constraints rc
                ON kcu.constraint_name = rc.constraint_name
               AND kcu.constraint_schema = rc.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = rc.unique_constraint_name
               AND ccu.constraint_schema = rc.constraint_schema
            WHERE kcu.table_name = 'episodic_notes'
              AND kcu.column_name = 'org_id'
            """
        )
        assert len(fk_rows) >= 1, "no FK found for org_id on episodic_notes"
        fk = fk_rows[0]
        assert fk["foreign_table"] == "org_projects", (
            f"FK target table: expected org_projects, got {fk['foreign_table']}"
        )
        assert fk["foreign_column"] == "id", (
            f"FK target column: expected id, got {fk['foreign_column']}"
        )
        assert fk["delete_rule"] == "SET NULL", (
            f"FK delete rule: expected SET NULL, got {fk['delete_rule']}"
        )

        # Check both new indexes exist
        idx_rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'episodic_notes'"
        )
        idx = {r["indexname"] for r in idx_rows}
        assert "ix_episodic_org_user_kind_recent" in idx, (
            "missing index ix_episodic_org_user_kind_recent"
        )
        assert "ix_episodic_org_tool_outcome" in idx, (
            "missing index ix_episodic_org_tool_outcome"
        )


async def test_009_downgrade_removes_column(test_db):
    """Round-trip: downgrade to 008_episodic_recorder, assert org_id gone,
    then upgrade back to head so subsequent tests are unaffected.
    """
    import os

    import asyncpg

    dsn = (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://breadmind:breadmind_dev@localhost:5434/breadmind"
    )

    migrator = Migrator(MigrationConfig(database_url=dsn))

    try:
        # Step down to 008
        migrator.downgrade("008_episodic_recorder")

        # Verify org_id column is gone
        probe = await asyncpg.connect(dsn, timeout=3)
        try:
            col_rows = await probe.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'episodic_notes'
                  AND column_name = 'org_id'
                """
            )
            assert len(col_rows) == 0, "org_id column still present after downgrade"

            idx_rows = await probe.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'episodic_notes'"
            )
            idx = {r["indexname"] for r in idx_rows}
            assert "ix_episodic_org_user_kind_recent" not in idx, (
                "ix_episodic_org_user_kind_recent still present after downgrade"
            )
            assert "ix_episodic_org_tool_outcome" not in idx, (
                "ix_episodic_org_tool_outcome still present after downgrade"
            )
        finally:
            await probe.close()
    finally:
        # Always restore to head so subsequent tests see a clean schema
        migrator.upgrade("head")
