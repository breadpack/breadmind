"""BackgroundJobManager — orchestrates background job lifecycle.

High-level API for creating, querying, pausing, resuming, and cancelling
background jobs. Uses BgJobsStore for persistence and Celery for execution.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class BackgroundJobManager:
    """High-level API for background job lifecycle management."""

    def __init__(self, store, redis_url: str = "", max_monitors: int = 10):
        self._store = store
        self._redis_url = redis_url
        self._max_monitors = max_monitors

    async def create_job(
        self,
        title: str,
        description: str,
        job_type: str,
        execution_plan: list[dict],
        user: str = "",
        channel: str = "",
        platform: str = "web",
        metadata: dict | None = None,
    ) -> dict:
        """Create a new background job and dispatch to Celery."""
        if job_type == "monitor":
            running = await self._store.list_all(status="running")
            monitor_count = sum(1 for j in running if j.get("job_type") == "monitor")
            if monitor_count >= self._max_monitors:
                raise ValueError(
                    f"Maximum concurrent monitors ({self._max_monitors}) reached"
                )

        job_id = await self._store.create(
            title=title,
            description=description,
            job_type=job_type,
            user=user,
            channel=channel,
            platform=platform,
            execution_plan=execution_plan,
            metadata=metadata,
        )

        from breadmind.tasks.celery_app import celery_app
        task_name = (
            "breadmind.execute_monitor_job"
            if job_type == "monitor"
            else "breadmind.execute_bg_job"
        )
        task = celery_app.send_task(task_name, args=[job_id])
        await self._store.update_status(job_id, "pending", celery_task_id=task.id)

        logger.info("Background job created: %s (%s)", job_id, title)
        return {"job_id": job_id, "celery_task_id": task.id}

    async def get_job(self, job_id: str) -> dict | None:
        return await self._store.get(job_id)

    async def list_jobs(self, status: str | None = None) -> list[dict]:
        return await self._store.list_all(status=status)

    async def pause_job(self, job_id: str) -> bool:
        job = await self._store.get(job_id)
        if not job or job["status"] != "running":
            return False
        from breadmind.tasks.celery_app import celery_app
        if job.get("celery_task_id"):
            celery_app.control.revoke(job["celery_task_id"], terminate=True)
        await self._store.update_status(job_id, "paused")
        logger.info("Job paused: %s", job_id)
        return True

    async def resume_job(self, job_id: str) -> bool:
        job = await self._store.get(job_id)
        if not job or job["status"] != "paused":
            return False
        from breadmind.tasks.celery_app import celery_app
        task_name = (
            "breadmind.execute_monitor_job"
            if job.get("job_type") == "monitor"
            else "breadmind.execute_bg_job"
        )
        task = celery_app.send_task(task_name, args=[job_id])
        await self._store.update_status(job_id, "running", celery_task_id=task.id)
        logger.info("Job resumed: %s", job_id)
        return True

    async def cancel_job(self, job_id: str) -> bool:
        job = await self._store.get(job_id)
        if not job or job["status"] in ("completed", "failed", "cancelled"):
            return False
        from breadmind.tasks.celery_app import celery_app
        if job.get("celery_task_id"):
            celery_app.control.revoke(job["celery_task_id"], terminate=True)
        await self._store.update_status(job_id, "cancelled")
        logger.info("Job cancelled: %s", job_id)
        return True

    async def delete_job(self, job_id: str) -> bool:
        job = await self._store.get(job_id)
        if not job or job["status"] not in ("completed", "failed", "cancelled"):
            return False
        await self._store.delete(job_id)
        return True

    async def recover_on_startup(self) -> int:
        """Re-dispatch jobs that were running when the server last stopped."""
        jobs = await self._store.list_all(status="running")
        recovered = 0
        from breadmind.tasks.celery_app import celery_app
        for job in jobs:
            task_name = (
                "breadmind.execute_monitor_job"
                if job.get("job_type") == "monitor"
                else "breadmind.execute_bg_job"
            )
            task = celery_app.send_task(task_name, args=[str(job["id"])])
            await self._store.update_status(
                str(job["id"]), "running", celery_task_id=task.id,
            )
            recovered += 1
            logger.info("Recovered job: %s (%s)", job["id"], job.get("title", ""))
        if recovered:
            logger.info("Recovered %d background jobs", recovered)
        return recovered

    async def cleanup_old_jobs(self, retention_days: int = 30) -> int:
        return await self._store.cleanup_old(retention_days)
