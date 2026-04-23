"""Database persistence for long-running coding jobs.

CRUD over ``coding_jobs`` / ``coding_phases`` (migration 007). Batch log
inserts via ``insert_log_batch`` arrive in a subsequent task; this module
currently covers only jobs and phases.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class JobStore:
    """Thin async CRUD layer for coding-job state.

    ``db`` is expected to expose an ``acquire()`` async context manager
    that yields an ``asyncpg.Connection`` (the project's
    :class:`breadmind.storage.database.Database` wrapper satisfies this).
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Jobs ────────────────────────────────────────────────────────────

    async def insert_job(
        self,
        *,
        job_id: str,
        project: str,
        agent: str,
        prompt: str,
        user_name: str,
        channel: str,
        started_at: datetime,
        status: str,
    ) -> None:
        """Insert a new job row. No-op if ``job_id`` already exists."""
        async with self._db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO coding_jobs (
                    id, project, agent, prompt, status,
                    user_name, channel, started_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (id) DO NOTHING
                """,
                job_id,
                project,
                agent,
                prompt,
                status,
                user_name,
                channel,
                started_at,
            )

    async def update_job(
        self,
        *,
        job_id: str,
        status: str,
        finished_at: datetime | None = None,
        duration_seconds: float | None = None,
        session_id: str = "",
        error: str = "",
        total_phases: int | None = None,
    ) -> None:
        """Patch mutable fields on a job row.

        ``session_id`` / ``error`` use empty-string as a "don't overwrite"
        sentinel so callers can supply partial updates without clobbering
        previously-set values. ``finished_at`` / ``duration_seconds`` /
        ``total_phases`` use ``None`` for the same purpose via ``COALESCE``.
        """
        async with self._db.acquire() as conn:
            await conn.execute(
                """
                UPDATE coding_jobs SET
                    status = $2,
                    finished_at = COALESCE($3, finished_at),
                    duration_seconds = COALESCE($4, duration_seconds),
                    session_id = CASE WHEN $5 <> '' THEN $5 ELSE session_id END,
                    error = CASE WHEN $6 <> '' THEN $6 ELSE error END,
                    total_phases = COALESCE($7, total_phases)
                WHERE id = $1
                """,
                job_id,
                status,
                finished_at,
                duration_seconds,
                session_id,
                error,
                total_phases,
            )

    async def get_job(self, job_id: str) -> dict | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM coding_jobs WHERE id = $1", job_id,
            )
            return dict(row) if row else None

    async def list_jobs(
        self,
        *,
        user_name: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return jobs newest-first, optionally filtered."""
        conds: list[str] = []
        args: list[Any] = []
        if user_name is not None:
            conds.append(f"user_name = ${len(args) + 1}")
            args.append(user_name)
        if status is not None:
            conds.append(f"status = ${len(args) + 1}")
            args.append(status)
        if since is not None:
            conds.append(f"started_at >= ${len(args) + 1}")
            args.append(since)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        args.append(int(limit))
        query = (
            f"SELECT * FROM coding_jobs {where} "
            f"ORDER BY started_at DESC LIMIT ${len(args)}"
        )
        async with self._db.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]

    # ── Phases ──────────────────────────────────────────────────────────

    async def insert_phases(
        self, job_id: str, phases: list[dict[str, Any]],
    ) -> None:
        """Bulk-insert phase rows. Silently skips duplicate (job_id, step)."""
        if not phases:
            return
        rows = [
            (
                job_id,
                int(p.get("step", i + 1)),
                str(p.get("title", f"Phase {i + 1}")),
                "pending",
            )
            for i, p in enumerate(phases)
        ]
        async with self._db.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO coding_phases (job_id, step, title, status)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT (job_id, step) DO NOTHING
                """,
                rows,
            )

    async def update_phase(
        self,
        *,
        job_id: str,
        step: int,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_seconds: float | None = None,
        output_summary: str = "",
        files_changed: list[str] | None = None,
    ) -> None:
        """Patch a phase row. Uses COALESCE/sentinel semantics akin to
        :meth:`update_job` so partial updates don't clobber prior state."""
        async with self._db.acquire() as conn:
            await conn.execute(
                """
                UPDATE coding_phases SET
                    status = $3,
                    started_at = COALESCE($4, started_at),
                    finished_at = COALESCE($5, finished_at),
                    duration_seconds = COALESCE($6, duration_seconds),
                    output_summary = CASE WHEN $7 <> '' THEN $7 ELSE output_summary END,
                    files_changed = COALESCE($8, files_changed)
                WHERE job_id = $1 AND step = $2
                """,
                job_id,
                step,
                status,
                started_at,
                finished_at,
                duration_seconds,
                output_summary,
                files_changed,
            )

    async def list_phases(self, job_id: str) -> list[dict]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM coding_phases WHERE job_id = $1 ORDER BY step",
                job_id,
            )
            return [dict(r) for r in rows]
