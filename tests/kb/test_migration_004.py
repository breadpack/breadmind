"""Tests for the 004_org_kb migration."""
from __future__ import annotations

from breadmind.storage.database import Database


EXPECTED_TABLES = {
    "org_projects",
    "org_project_members",
    "org_channel_map",
    "org_knowledge",
    "kb_sources",
    "promotion_candidates",
    "connector_sync_state",
    "kb_audit_log",
    "redaction_vocab",
}


async def test_org_kb_tables_exist(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY($1::text[])
            """,
            list(EXPECTED_TABLES),
        )
    found = {r["table_name"] for r in rows}
    assert found == EXPECTED_TABLES


async def test_pgvector_extension_enabled(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        )
    assert row is not None


async def test_org_knowledge_embedding_hnsw_index(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'org_knowledge'
            """
        )
    names = {r["indexname"] for r in rows}
    assert "idx_org_kn_embedding" in names
    assert "idx_org_kn_project" in names


async def test_promotion_candidates_status_index(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'promotion_candidates'
            """
        )
    names = {r["indexname"] for r in rows}
    assert "idx_promo_project_status" in names


async def test_audit_log_indexes(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'kb_audit_log'
            """
        )
    names = {r["indexname"] for r in rows}
    assert "idx_audit_actor_ts" in names
    assert "idx_audit_project_ts" in names


async def test_connector_sync_state_unique(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        await conn.execute(
            "INSERT INTO connector_sync_state (connector, scope_key) "
            "VALUES ('confluence', 'space-a')"
        )
        try:
            import asyncpg
            try:
                await conn.execute(
                    "INSERT INTO connector_sync_state (connector, scope_key) "
                    "VALUES ('confluence', 'space-a')"
                )
                duplicate_inserted = True
            except asyncpg.UniqueViolationError:
                duplicate_inserted = False
        finally:
            await conn.execute(
                "DELETE FROM connector_sync_state WHERE connector='confluence'"
            )
    assert duplicate_inserted is False
