"""Tests for the 006_connector_configs migration."""
from __future__ import annotations

from breadmind.storage.database import Database


async def test_connector_configs_table_exists(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.connector_configs') IS NOT NULL"
        )
    assert exists


async def test_connector_configs_has_expected_columns(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='connector_configs'"
        )
    names = {r["column_name"] for r in cols}
    assert {
        "id",
        "connector",
        "project_id",
        "scope_key",
        "settings",
        "enabled",
        "created_at",
    }.issubset(names)


async def test_connector_configs_unique_constraint(test_db: Database) -> None:
    """UNIQUE (connector, scope_key) must be enforced."""
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tc.constraint_type, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_name = kcu.table_name
            WHERE tc.table_name = 'connector_configs'
              AND tc.constraint_type = 'UNIQUE'
            """
        )
    unique_cols = {r["column_name"] for r in rows}
    assert "connector" in unique_cols
    assert "scope_key" in unique_cols


async def test_connector_configs_index_exists(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename='connector_configs'"
        )
    names = {r["indexname"] for r in rows}
    assert "idx_connector_configs_enabled" in names
