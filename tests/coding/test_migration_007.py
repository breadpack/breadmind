"""Tests for the 007_coding_jobs migration.

The shared ``test_db`` fixture (see ``tests/conftest.py``) already
runs ``Migrator.upgrade("head")`` before yielding the connection,
so by the time these tests execute the 007 schema must be in place.
"""
from __future__ import annotations

from breadmind.storage.database import Database


async def test_007_creates_three_tables(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        tables = {
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        }
        assert {"coding_jobs", "coding_phases", "coding_phase_logs"} <= tables

        idx = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
            )
        }
        assert "idx_coding_jobs_user_started" in idx
        assert "idx_coding_jobs_status_started" in idx
        assert "idx_phase_logs_job_step_line" in idx
        assert "idx_phase_logs_ts_brin" in idx


async def test_007_cascade_delete(test_db: Database) -> None:
    async with test_db.acquire() as conn:
        # Clean up any residue from previous runs so this test is
        # idempotent against the shared Postgres instance.
        await conn.execute("DELETE FROM coding_jobs WHERE id='j1'")

        await conn.execute(
            "INSERT INTO coding_jobs (id, project, agent, prompt, status, started_at) "
            "VALUES ('j1','p','claude','test','pending', now())"
        )
        await conn.execute(
            "INSERT INTO coding_phases (job_id, step, title, status) "
            "VALUES ('j1', 1, 'step1', 'pending')"
        )
        await conn.execute(
            "INSERT INTO coding_phase_logs (job_id, step, line_no, text) "
            "VALUES ('j1', 1, 1, 'hello')"
        )
        await conn.execute("DELETE FROM coding_jobs WHERE id='j1'")

        phase_cnt = await conn.fetchval(
            "SELECT count(*) FROM coding_phases WHERE job_id='j1'"
        )
        log_cnt = await conn.fetchval(
            "SELECT count(*) FROM coding_phase_logs WHERE job_id='j1'"
        )
        assert phase_cnt == 0
        assert log_cnt == 0
