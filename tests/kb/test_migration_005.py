"""Tests for the 005_kb_p3_feedback migration."""
from __future__ import annotations

from breadmind.storage.database import Database


async def test_kb_feedback_table_exists(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.kb_feedback') IS NOT NULL"
        )
    assert exists


async def test_kb_extraction_pause_table_exists(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.kb_extraction_pause') IS NOT NULL"
        )
    assert exists


async def test_org_knowledge_has_rank_and_flag(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='org_knowledge'"
        )
    names = {r["column_name"] for r in cols}
    assert "rank_weight" in names
    assert "flag_count" in names


async def test_promotion_candidates_has_sensitive_flag(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='promotion_candidates'"
        )
    names = {r["column_name"] for r in cols}
    assert "sensitive_flag" in names


async def test_kb_feedback_indexes_exist(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename='kb_feedback'"
        )
    names = {r["indexname"] for r in rows}
    assert "idx_kb_feedback_knowledge" in names
    assert "idx_kb_feedback_user_ts" in names
