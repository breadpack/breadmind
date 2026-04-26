"""Persistence shim for kb_backfill_jobs row lifecycle.

Spec: docs/superpowers/specs/2026-04-26-backfill-pipeline-slack-design.md (T9)

JobCheckpointer owns the kb_backfill_jobs row lifecycle:
``start()`` (insert running row) → ``checkpoint()`` × N (update last_cursor /
progress / skipped JSONB columns on a 50-item / 30-second cadence) →
``finish()`` (mark completed | paused | failed and stamp finished_at).

The runner (T8) integrates this so a job can resume from ``last_cursor`` on
restart via :func:`load_resume_cursor`.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from breadmind.storage.database import Database


@dataclass
class JobCheckpointer:
    """Owns kb_backfill_jobs row lifecycle: start → N×checkpoint → finish."""

    db: Database

    async def start(
        self,
        *,
        org_id: uuid.UUID,
        source_kind: str,
        source_filter: dict,
        instance_id: str,
        since: datetime,
        until: datetime,
        dry_run: bool,
        token_budget: int,
        created_by: str,
    ) -> uuid.UUID:
        row = await self.db.fetchrow(
            """
            INSERT INTO kb_backfill_jobs
                (org_id, source_kind, source_filter, instance_id,
                 since_ts, until_ts, dry_run, token_budget,
                 status, started_at, created_by)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8,
                    'running', now(), $9)
            RETURNING id
            """,
            org_id,
            source_kind,
            json.dumps(source_filter),
            instance_id,
            since,
            until,
            dry_run,
            token_budget,
            created_by,
        )
        return row["id"]

    async def checkpoint(
        self,
        *,
        job_id: uuid.UUID,
        cursor: str | None,
        progress: dict,
        skipped: dict[str, int],
    ) -> None:
        await self.db.execute(
            """
            UPDATE kb_backfill_jobs
                SET last_cursor   = $2,
                    progress_json = $3::jsonb,
                    skipped_json  = $4::jsonb
              WHERE id = $1
            """,
            job_id,
            cursor,
            json.dumps(progress),
            json.dumps(skipped),
        )

    async def finish(
        self,
        *,
        job_id: uuid.UUID,
        status: str,
        error: str | None = None,
    ) -> None:
        await self.db.execute(
            """
            UPDATE kb_backfill_jobs
                SET status = $2, finished_at = now(), error = $3
              WHERE id = $1
            """,
            job_id,
            status,
            error,
        )


async def load_resume_cursor(db: Database, job_id: uuid.UUID) -> str | None:
    """Return the last persisted cursor for a job, or None if absent."""
    row = await db.fetchrow(
        "SELECT last_cursor FROM kb_backfill_jobs WHERE id=$1",
        job_id,
    )
    return row["last_cursor"] if row else None
