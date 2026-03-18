"""Background jobs database operations.

Provides CRUD methods for the bg_jobs table, used by BackgroundJobManager.
Requires a Database instance with asyncpg connection pool.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BgJobsStore:
    """Database operations for background jobs."""

    def __init__(self, db) -> None:
        self._db = db

    async def create(
        self,
        title: str,
        description: str,
        job_type: str,
        user: str,
        channel: str,
        platform: str,
        execution_plan: list[dict],
        metadata: dict | None = None,
    ) -> str:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO bg_jobs (title, description, job_type, "user", channel, platform,
                                     execution_plan, metadata, progress)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb,
                        jsonb_build_object(
                            'last_completed_step', 0,
                            'total_steps', $9::int,
                            'message', '',
                            'percentage', 0
                        ))
                RETURNING id
            """, title, description, job_type, user, channel, platform,
                 json.dumps(execution_plan),
                 json.dumps(metadata or {}),
                 len(execution_plan))
            return str(row["id"])

    async def get(self, job_id: str) -> dict | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bg_jobs WHERE id = $1::uuid", job_id,
            )
            return dict(row) if row else None

    async def list_all(
        self, status: str | None = None, user: str | None = None,
    ) -> list[dict]:
        async with self._db.acquire() as conn:
            query = "SELECT * FROM bg_jobs"
            conditions: list[str] = []
            params: list[Any] = []
            if status:
                params.append(status)
                conditions.append(f"status = ${len(params)}")
            if user:
                params.append(user)
                conditions.append(f'"user" = ${len(params)}')
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC"
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    async def update_status(self, job_id: str, status: str, **kwargs) -> None:
        async with self._db.acquire() as conn:
            sets = ["status = $2", "updated_at = NOW()"]
            params: list[Any] = [job_id, status]

            if status == "running" and "started_at" not in kwargs:
                sets.append("started_at = COALESCE(started_at, NOW())")
            if status in ("completed", "failed", "cancelled") and "completed_at" not in kwargs:
                sets.append("completed_at = NOW()")

            for key, val in kwargs.items():
                params.append(val)
                if key in ("progress", "metadata", "execution_plan"):
                    sets.append(f"{key} = ${len(params)}::jsonb")
                else:
                    sets.append(f'"{key}" = ${len(params)}')

            await conn.execute(
                f"UPDATE bg_jobs SET {', '.join(sets)} WHERE id = $1::uuid",
                *params,
            )

    async def update_progress(
        self, job_id: str, step: int, message: str, percentage: int | None = None,
    ) -> None:
        async with self._db.acquire() as conn:
            progress: dict[str, Any] = {
                "last_completed_step": step,
                "message": message,
            }
            if percentage is not None:
                progress["percentage"] = percentage
            await conn.execute("""
                UPDATE bg_jobs
                SET progress = progress || $2::jsonb, updated_at = NOW()
                WHERE id = $1::uuid
            """, job_id, json.dumps(progress))

    async def delete(self, job_id: str) -> None:
        async with self._db.acquire() as conn:
            await conn.execute(
                "DELETE FROM bg_jobs WHERE id = $1::uuid "
                "AND status IN ('completed', 'failed', 'cancelled')",
                job_id,
            )

    async def cleanup_old(self, retention_days: int = 30) -> int:
        async with self._db.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM bg_jobs
                WHERE status IN ('completed', 'failed', 'cancelled')
                AND completed_at < NOW() - INTERVAL '1 day' * $1
            """, retention_days)
            # result is like "DELETE 5"
            try:
                return int(result.split()[-1])
            except (ValueError, IndexError):
                return 0
