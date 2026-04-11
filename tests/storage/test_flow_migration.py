"""Tests for the 002_flow_events migration.

Verifies that the flow durable-task tables and their required
indexes are created when alembic is upgraded to head.
"""
from __future__ import annotations

from breadmind.storage.database import Database


async def test_flow_tables_exist(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        result = await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('flow_events', 'flows', 'flow_steps')
            ORDER BY table_name
            """
        )
    assert [r["table_name"] for r in result] == [
        "flow_events",
        "flow_steps",
        "flows",
    ]


async def test_flow_events_append_only_index(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'flow_events'
            """
        )
    names = {r["indexname"] for r in rows}
    assert "idx_flow_events_flow" in names
    assert "idx_flow_events_type_time" in names


async def test_flows_user_status_index(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'flows'
            """
        )
    names = {r["indexname"] for r in rows}
    assert "idx_flows_user_status" in names


async def test_flow_steps_status_index(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'flow_steps'
            """
        )
    names = {r["indexname"] for r in rows}
    assert "idx_flow_steps_status" in names
