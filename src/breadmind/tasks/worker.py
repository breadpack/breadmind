"""Celery task definitions and worker bootstrap.

Worker runs in a separate process with its own ToolRegistry, DB connection,
and SafetyGuard. Async tools are called via asyncio.run() bridge.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import redis as sync_redis
from celery.signals import worker_process_init

from breadmind.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ── Worker-local singletons ─────────────────────────────────────────

_db = None
_store = None
_registry = None
_guard = None
_redis_client = None


@worker_process_init.connect
def _worker_bootstrap(**kwargs):
    """Initialize BreadMind components in the worker process."""
    global _db, _store, _registry, _guard, _redis_client
    logger.info("Worker bootstrap starting...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # DB
    dsn = os.environ.get("BREADMIND_DSN", "")
    if dsn:
        from breadmind.storage.database import Database
        _db = Database(dsn)
        loop.run_until_complete(_db.connect())

        from breadmind.storage.bg_jobs_store import BgJobsStore
        _store = BgJobsStore(_db)

    # ToolRegistry + SafetyGuard
    from breadmind.tools.registry import ToolRegistry
    from breadmind.tools.builtin import register_builtin_tools
    from breadmind.core.safety import SafetyGuard
    from breadmind.config import load_safety_config

    _registry = ToolRegistry()
    register_builtin_tools(_registry)
    _guard = SafetyGuard(load_safety_config())

    # Redis for Pub/Sub
    from breadmind.constants import DEFAULT_REDIS_URL
    redis_url = os.environ.get("BREADMIND_REDIS_URL", DEFAULT_REDIS_URL)
    try:
        _redis_client = sync_redis.from_url(redis_url)
        _redis_client.ping()
    except Exception:
        logger.warning("Redis not available for Pub/Sub")
        _redis_client = None

    logger.info("Worker bootstrap complete. Tools: %d", len(_registry.list_tools()))


def _publish(job_id: str, data: dict) -> None:
    """Publish progress to Redis Pub/Sub."""
    if _redis_client:
        try:
            _redis_client.publish(
                f"breadmind:bg_job:{job_id}",
                json.dumps(data, default=str),
            )
        except Exception:
            pass


# ── Single Job Execution ─────────────────────────────────────────────

@celery_app.task(bind=True, name="breadmind.execute_bg_job")
def execute_bg_job(self, job_id: str):
    """Execute a single-type background job."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run_single(job_id))
    except Exception as e:
        logger.exception("Background job %s failed", job_id)
        loop.run_until_complete(_mark_failed(job_id, str(e)))
    finally:
        loop.close()


async def _run_single(job_id: str) -> None:
    if not _store:
        raise RuntimeError("Worker DB not initialized")

    job = await _store.get(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    await _store.update_status(job_id, "running")
    _publish(job_id, {"type": "started", "job_id": job_id})

    plan = job.get("execution_plan") or []
    if isinstance(plan, str):
        plan = json.loads(plan)

    progress = job.get("progress") or {}
    if isinstance(progress, str):
        progress = json.loads(progress)
    start_step = progress.get("last_completed_step", 0)
    total = len(plan)

    results = []
    for i, step in enumerate(plan[start_step:], start=start_step):
        # Check for pause/cancel
        current = await _store.get(job_id)
        if not current or current["status"] in ("cancelled", "paused"):
            logger.info("Job %s %s at step %d", job_id, current["status"] if current else "gone", i)
            return

        tool_name = step.get("tool", "")
        tool_args = step.get("args", {})
        description = step.get("description", f"Step {i + 1}")

        pct = int((i / total) * 100) if total > 0 else 0
        await _store.update_progress(job_id, i, f"Executing: {description}", pct)
        _publish(job_id, {
            "type": "progress", "job_id": job_id,
            "step": i + 1, "total": total,
            "message": description, "percentage": pct,
        })

        # Execute tool
        try:
            if _registry and _registry.has_tool(tool_name):
                result = await _registry.execute(tool_name, tool_args)
                results.append({"step": i + 1, "description": description, "output": result.output})
            else:
                results.append({"step": i + 1, "description": description, "output": f"Tool '{tool_name}' not found"})
        except Exception as e:
            results.append({"step": i + 1, "description": description, "error": str(e)})
            logger.warning("Step %d failed: %s", i + 1, e)

        await _store.update_progress(
            job_id, i + 1, f"Completed: {description}",
            int(((i + 1) / total) * 100) if total > 0 else 100,
        )

    # Completion
    from breadmind.storage.credential_vault import CredentialVault
    result_text = json.dumps(results, ensure_ascii=False, indent=2)
    result_text = CredentialVault.sanitize_text(result_text)

    max_kb = int(os.environ.get("BREADMIND_RESULT_MAX_KB", "100"))
    if len(result_text) > max_kb * 1024:
        result_text = result_text[: max_kb * 1024] + "\n... [truncated]"

    await _store.update_status(job_id, "completed", result=result_text)
    await _store.update_progress(job_id, total, "Completed", 100)
    _publish(job_id, {"type": "completed", "job_id": job_id})


# ── Monitor Job Execution ────────────────────────────────────────────

@celery_app.task(bind=True, name="breadmind.execute_monitor_job")
def execute_monitor_job(self, job_id: str):
    """Execute a monitor-type background job."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run_monitor(job_id))
    except Exception as e:
        logger.exception("Monitor job %s failed", job_id)
        loop.run_until_complete(_mark_failed(job_id, str(e)))
    finally:
        loop.close()


async def _run_monitor(job_id: str) -> None:
    if not _store:
        raise RuntimeError("Worker DB not initialized")

    job = await _store.get(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    await _store.update_status(job_id, "running")

    meta = job.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    config = meta.get("monitor_config", {})
    interval = config.get("interval_seconds", 60)
    check_tool = config.get("check_tool", "shell_exec")
    check_args = config.get("check_args", {})

    iteration = 0
    while True:
        current = await _store.get(job_id)
        if not current or current["status"] in ("cancelled", "paused"):
            logger.info("Monitor job %s stopped", job_id)
            return

        iteration += 1
        await _store.update_progress(job_id, iteration, f"Check #{iteration}")
        _publish(job_id, {
            "type": "progress", "job_id": job_id,
            "message": f"Monitor check #{iteration}",
            "iteration": iteration,
        })

        try:
            if _registry and _registry.has_tool(check_tool):
                await _registry.execute(check_tool, check_args)
        except Exception as e:
            logger.warning("Monitor check failed: %s", e)
            _publish(job_id, {
                "type": "alert", "job_id": job_id,
                "message": f"Check failed: {e}",
                "iteration": iteration,
            })

        await asyncio.sleep(interval)


# ── Helpers ──────────────────────────────────────────────────────────

async def _mark_failed(job_id: str, error: str) -> None:
    if _store:
        await _store.update_status(job_id, "failed", error=error)
        _publish(job_id, {"type": "failed", "job_id": job_id, "error": error})
