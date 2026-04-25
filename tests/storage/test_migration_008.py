"""Tests for migration 008 — episodic recorder schema additions.

The ``test_db`` fixture (from ``tests/conftest.py``) connects to a live
Postgres instance and upgrades to head before yielding, so by the time
these assertions run the 008 migration has already been applied.
"""
from __future__ import annotations

import pytest


async def test_migration_008_adds_columns_and_indexes(test_db):
    async with test_db.acquire() as conn:
        cols = {
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'episodic_notes'"
            )
        }
        for c in (
            "kind", "tool_name", "tool_args_digest", "outcome",
            "session_id", "user_id", "summary", "pinned",
        ):
            assert c in cols, f"missing column {c}"

        idx = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'episodic_notes'"
            )
        }
        assert "ix_episodic_user_kind_recent" in idx
        assert "ix_episodic_user_tool_outcome" in idx
        assert "ix_episodic_keywords_gin" in idx
