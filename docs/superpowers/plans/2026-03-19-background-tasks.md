# Background Task System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Celery + Redis 기반 백그라운드 작업 시스템을 구축하여 장시간 작업의 영속적 실행/일시정지/재개/취소를 지원한다.

**Architecture:** BackgroundJobManager가 작업 CRUD를 관리하고, Celery Worker가 별도 프로세스에서 BreadMind 도구를 실행한다. Redis Pub/Sub으로 Worker→Web Server 실시간 알림을 전달하고, DB에 작업 상태를 영속한다.

**Tech Stack:** Celery, Redis (aioredis), asyncpg (PostgreSQL), gevent

**Spec:** `docs/superpowers/specs/2026-03-19-background-tasks-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/breadmind/tasks/__init__.py` | Package init |
| `src/breadmind/tasks/celery_app.py` | Celery app instance, Redis config |
| `src/breadmind/tasks/worker.py` | Celery task definitions, worker_bootstrap, async bridge |
| `src/breadmind/tasks/manager.py` | BackgroundJobManager — CRUD, pause/resume/cancel |
| `src/breadmind/web/routes/bg_jobs.py` | REST API endpoints for bg-jobs |

### Modified Files
| File | Changes |
|------|---------|
| `src/breadmind/storage/database.py` | Add `bg_jobs` table + CRUD methods |
| `src/breadmind/tools/builtin.py` | Add `run_background` tool |
| `src/breadmind/config.py` | Add `TaskConfig` dataclass |
| `src/breadmind/core/bootstrap.py` | Init BackgroundJobManager, recovery |
| `src/breadmind/web/app.py` | Register bg_jobs router, Redis listener |

---

## Chunk 1: Database Layer + Config

### Task 1: Add TaskConfig to config.py

**Files:**
- Modify: `src/breadmind/config.py`

- [ ] **Step 1: Add TaskConfig dataclass**

```python
@dataclass
class TaskConfig:
    redis_url: str = "redis://localhost:6379/0"
    max_concurrent_monitors: int = 10
    result_max_size_kb: int = 100
    completed_retention_days: int = 30
```

Add `task: TaskConfig = field(default_factory=TaskConfig)` to the main `Config` class.

- [ ] **Step 2: Add BREADMIND_REDIS_URL env var loading**

In the env loading section, add:
```python
redis_url = os.environ.get("BREADMIND_REDIS_URL")
if redis_url:
    config.task.redis_url = redis_url
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/config.py
git commit -m "feat(config): add TaskConfig for background jobs"
```

### Task 2: Add bg_jobs table and CRUD to database.py

**Files:**
- Modify: `src/breadmind/storage/database.py`

- [ ] **Step 1: Add bg_jobs CREATE TABLE to _migrate()**

Add to the existing `_migrate()` method's SQL:

```sql
CREATE TABLE IF NOT EXISTS bg_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    celery_task_id VARCHAR(255),
    title VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    job_type VARCHAR(20) NOT NULL DEFAULT 'single',
    "user" VARCHAR(100) DEFAULT '',
    channel VARCHAR(200) DEFAULT '',
    platform VARCHAR(20) DEFAULT 'web',
    progress JSONB DEFAULT '{"last_completed_step": 0, "total_steps": 0, "message": "", "percentage": 0}',
    result TEXT,
    error TEXT,
    execution_plan JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_bg_jobs_status ON bg_jobs(status);
CREATE INDEX IF NOT EXISTS idx_bg_jobs_user ON bg_jobs("user");
```

- [ ] **Step 2: Add CRUD methods**

```python
async def create_bg_job(self, title, description, job_type, user, channel, platform, execution_plan, metadata=None):
    async with self.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO bg_jobs (title, description, job_type, "user", channel, platform, execution_plan, metadata,
                                 progress)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                    jsonb_build_object('last_completed_step', 0, 'total_steps', $9::int, 'message', '', 'percentage', 0))
            RETURNING id
        """, title, description, job_type, user, channel, platform,
             json.dumps(execution_plan), json.dumps(metadata or {}),
             len(execution_plan))
        return str(row["id"])

async def get_bg_job(self, job_id):
    async with self.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM bg_jobs WHERE id = $1", job_id)
        if row:
            return dict(row)
        return None

async def list_bg_jobs(self, status=None, user=None):
    async with self.acquire() as conn:
        query = "SELECT * FROM bg_jobs"
        conditions = []
        params = []
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

async def update_bg_job_status(self, job_id, status, **kwargs):
    async with self.acquire() as conn:
        sets = ["status = $2", "updated_at = NOW()"]
        params = [job_id, status]
        for key, val in kwargs.items():
            params.append(val)
            if key in ("progress", "metadata", "execution_plan"):
                sets.append(f"{key} = ${len(params)}::jsonb")
            else:
                sets.append(f"{key} = ${len(params)}")
        await conn.execute(
            f"UPDATE bg_jobs SET {', '.join(sets)} WHERE id = $1",
            *params,
        )

async def update_bg_job_progress(self, job_id, step, message, percentage=None):
    async with self.acquire() as conn:
        progress = {"last_completed_step": step, "message": message}
        if percentage is not None:
            progress["percentage"] = percentage
        await conn.execute("""
            UPDATE bg_jobs
            SET progress = progress || $2::jsonb, updated_at = NOW()
            WHERE id = $1
        """, job_id, json.dumps(progress))

async def delete_bg_job(self, job_id):
    async with self.acquire() as conn:
        await conn.execute(
            "DELETE FROM bg_jobs WHERE id = $1 AND status IN ('completed', 'failed', 'cancelled')",
            job_id,
        )

async def cleanup_old_bg_jobs(self, retention_days=30):
    async with self.acquire() as conn:
        await conn.execute("""
            DELETE FROM bg_jobs
            WHERE status IN ('completed', 'failed', 'cancelled')
            AND completed_at < NOW() - INTERVAL '1 day' * $1
        """, retention_days)
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/storage/database.py
git commit -m "feat(db): add bg_jobs table and CRUD methods"
```

---

## Chunk 2: Celery App + Worker

### Task 3: Create Celery app

**Files:**
- Create: `src/breadmind/tasks/__init__.py`
- Create: `src/breadmind/tasks/celery_app.py`

- [ ] **Step 1: Create package init**

```python
# src/breadmind/tasks/__init__.py
```

- [ ] **Step 2: Create celery_app.py**

```python
"""Celery application instance for background jobs."""
import os
from celery import Celery

_redis_url = os.environ.get("BREADMIND_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "breadmind",
    broker=_redis_url,
    backend=_redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    imports=["breadmind.tasks.worker"],
)
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/tasks/
git commit -m "feat(tasks): create Celery app with Redis config"
```

### Task 4: Create worker with bootstrap and async bridge

**Files:**
- Create: `src/breadmind/tasks/worker.py`

- [ ] **Step 1: Create worker.py**

```python
"""Celery task definitions and worker bootstrap."""
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
_registry = None
_guard = None
_redis_client = None


@worker_process_init.connect
def _worker_bootstrap(**kwargs):
    """Initialize BreadMind components in the worker process."""
    global _db, _registry, _guard, _redis_client
    logger.info("Worker bootstrap starting...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # DB
    from breadmind.storage.database import Database
    dsn = os.environ.get("BREADMIND_DSN", "")
    if dsn:
        _db = Database(dsn)
        loop.run_until_complete(_db.connect())

    # ToolRegistry + SafetyGuard
    from breadmind.tools.registry import ToolRegistry
    from breadmind.tools.builtin import register_builtin_tools
    from breadmind.core.safety import SafetyGuard
    from breadmind.config import load_safety_config

    _registry = ToolRegistry()
    register_builtin_tools(_registry)
    _guard = SafetyGuard(load_safety_config())

    # Redis for Pub/Sub
    redis_url = os.environ.get("BREADMIND_REDIS_URL", "redis://localhost:6379/0")
    _redis_client = sync_redis.from_url(redis_url)

    logger.info("Worker bootstrap complete. Tools: %d", len(_registry.list_tools()))


def _publish_progress(job_id: str, data: dict):
    """Publish progress to Redis Pub/Sub."""
    if _redis_client:
        channel = f"breadmind:bg_job:{job_id}"
        _redis_client.publish(channel, json.dumps(data))


# ── Celery Tasks ─────────────────────────────────────────────────────

@celery_app.task(bind=True, name="breadmind.execute_bg_job")
def execute_bg_job(self, job_id: str):
    """Execute a background job — single or monitor type."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_execute_single_job(self, job_id))
    except Exception as e:
        logger.exception("Background job %s failed", job_id)
        loop.run_until_complete(_mark_failed(job_id, str(e)))
    finally:
        loop.close()


async def _execute_single_job(celery_task, job_id: str):
    """Execute a single-type background job step by step."""
    if not _db:
        raise RuntimeError("Worker DB not initialized")

    job = await _db.get_bg_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    # Mark as running
    await _db.update_bg_job_status(job_id, "running", started_at="NOW()")
    _publish_progress(job_id, {"type": "started", "job_id": job_id})

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
        current = await _db.get_bg_job(job_id)
        current_status = current["status"] if current else "cancelled"
        if current_status == "cancelled":
            logger.info("Job %s cancelled", job_id)
            return
        if current_status == "paused":
            logger.info("Job %s paused at step %d", job_id, i)
            return  # Worker exits; resume will re-dispatch

        tool_name = step.get("tool", "")
        tool_args = step.get("args", {})
        description = step.get("description", f"Step {i + 1}")

        # Progress update
        pct = int((i / total) * 100) if total > 0 else 0
        await _db.update_bg_job_progress(job_id, i, f"Executing: {description}", pct)
        _publish_progress(job_id, {
            "type": "progress",
            "job_id": job_id,
            "step": i + 1,
            "total": total,
            "message": description,
            "percentage": pct,
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

        # Mark step as completed
        await _db.update_bg_job_progress(job_id, i + 1, f"Completed: {description}",
                                          int(((i + 1) / total) * 100) if total > 0 else 100)

    # Completion
    from breadmind.storage.credential_vault import CredentialVault
    result_text = json.dumps(results, ensure_ascii=False, indent=2)
    result_text = CredentialVault.sanitize_text(result_text)

    # Truncate if too large
    max_kb = int(os.environ.get("BREADMIND_RESULT_MAX_KB", "100"))
    if len(result_text) > max_kb * 1024:
        result_text = result_text[:max_kb * 1024] + "\n... [truncated]"

    await _db.update_bg_job_status(
        job_id, "completed",
        result=result_text,
        completed_at="NOW()",
    )
    await _db.update_bg_job_progress(job_id, total, "Completed", 100)
    _publish_progress(job_id, {"type": "completed", "job_id": job_id})


@celery_app.task(bind=True, name="breadmind.execute_monitor_job")
def execute_monitor_job(self, job_id: str):
    """Execute a monitor-type background job."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_execute_monitor(self, job_id))
    except Exception as e:
        logger.exception("Monitor job %s failed", job_id)
        loop.run_until_complete(_mark_failed(job_id, str(e)))
    finally:
        loop.close()


async def _execute_monitor(celery_task, job_id: str):
    """Execute a monitor job — periodic check loop."""
    if not _db:
        raise RuntimeError("Worker DB not initialized")

    job = await _db.get_bg_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    await _db.update_bg_job_status(job_id, "running", started_at="NOW()")

    meta = job.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    config = meta.get("monitor_config", {})
    interval = config.get("interval_seconds", 60)
    check_tool = config.get("check_tool", "shell_exec")
    check_args = config.get("check_args", {})

    iteration = 0
    while True:
        # Check for cancel/pause
        current = await _db.get_bg_job(job_id)
        current_status = current["status"] if current else "cancelled"
        if current_status in ("cancelled", "paused"):
            logger.info("Monitor job %s %s", job_id, current_status)
            return

        iteration += 1
        await _db.update_bg_job_progress(
            job_id, iteration, f"Check #{iteration}", 0,
        )
        _publish_progress(job_id, {
            "type": "progress",
            "job_id": job_id,
            "message": f"Monitor check #{iteration}",
            "iteration": iteration,
        })

        # Execute check
        try:
            if _registry and _registry.has_tool(check_tool):
                await _registry.execute(check_tool, check_args)
        except Exception as e:
            logger.warning("Monitor check failed: %s", e)
            _publish_progress(job_id, {
                "type": "alert",
                "job_id": job_id,
                "message": f"Check failed: {e}",
                "iteration": iteration,
            })

        await asyncio.sleep(interval)


async def _mark_failed(job_id: str, error: str):
    if _db:
        await _db.update_bg_job_status(
            job_id, "failed", error=error, completed_at="NOW()",
        )
        _publish_progress(job_id, {"type": "failed", "job_id": job_id, "error": error})
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/tasks/worker.py
git commit -m "feat(tasks): add Celery worker with async bridge and job execution"
```

---

## Chunk 3: BackgroundJobManager + API

### Task 5: Create BackgroundJobManager

**Files:**
- Create: `src/breadmind/tasks/manager.py`

- [ ] **Step 1: Create manager.py**

```python
"""BackgroundJobManager — orchestrates background job lifecycle."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BackgroundJobManager:
    """High-level API for creating, querying, and controlling background jobs."""

    def __init__(self, db, redis_url: str = "", max_monitors: int = 10):
        self._db = db
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
        # Monitor limit check
        if job_type == "monitor":
            running = await self._db.list_bg_jobs(status="running")
            monitor_count = sum(1 for j in running if j.get("job_type") == "monitor")
            if monitor_count >= self._max_monitors:
                raise ValueError(
                    f"Maximum concurrent monitors ({self._max_monitors}) reached"
                )

        job_id = await self._db.create_bg_job(
            title=title,
            description=description,
            job_type=job_type,
            user=user,
            channel=channel,
            platform=platform,
            execution_plan=execution_plan,
            metadata=metadata,
        )

        # Dispatch to Celery
        from breadmind.tasks.celery_app import celery_app
        if job_type == "monitor":
            task = celery_app.send_task(
                "breadmind.execute_monitor_job", args=[job_id],
            )
        else:
            task = celery_app.send_task(
                "breadmind.execute_bg_job", args=[job_id],
            )

        await self._db.update_bg_job_status(
            job_id, "pending", celery_task_id=task.id,
        )

        logger.info("Background job created: %s (%s)", job_id, title)
        return {"job_id": job_id, "celery_task_id": task.id}

    async def get_job(self, job_id: str) -> dict | None:
        return await self._db.get_bg_job(job_id)

    async def list_jobs(self, status: str | None = None) -> list[dict]:
        return await self._db.list_bg_jobs(status=status)

    async def pause_job(self, job_id: str) -> bool:
        job = await self._db.get_bg_job(job_id)
        if not job or job["status"] != "running":
            return False
        # Revoke Celery task (terminate=True for gevent)
        from breadmind.tasks.celery_app import celery_app
        if job.get("celery_task_id"):
            celery_app.control.revoke(job["celery_task_id"], terminate=True)
        await self._db.update_bg_job_status(job_id, "paused")
        logger.info("Job paused: %s", job_id)
        return True

    async def resume_job(self, job_id: str) -> bool:
        job = await self._db.get_bg_job(job_id)
        if not job or job["status"] != "paused":
            return False
        # Re-dispatch from last completed step
        from breadmind.tasks.celery_app import celery_app
        if job.get("job_type") == "monitor":
            task = celery_app.send_task(
                "breadmind.execute_monitor_job", args=[job_id],
            )
        else:
            task = celery_app.send_task(
                "breadmind.execute_bg_job", args=[job_id],
            )
        await self._db.update_bg_job_status(
            job_id, "running", celery_task_id=task.id,
        )
        logger.info("Job resumed: %s", job_id)
        return True

    async def cancel_job(self, job_id: str) -> bool:
        job = await self._db.get_bg_job(job_id)
        if not job or job["status"] in ("completed", "failed", "cancelled"):
            return False
        from breadmind.tasks.celery_app import celery_app
        if job.get("celery_task_id"):
            celery_app.control.revoke(job["celery_task_id"], terminate=True)
        await self._db.update_bg_job_status(
            job_id, "cancelled", completed_at="NOW()",
        )
        logger.info("Job cancelled: %s", job_id)
        return True

    async def delete_job(self, job_id: str) -> bool:
        job = await self._db.get_bg_job(job_id)
        if not job or job["status"] not in ("completed", "failed", "cancelled"):
            return False
        await self._db.delete_bg_job(job_id)
        return True

    async def recover_on_startup(self):
        """Recover jobs that were running when the server last stopped."""
        jobs = await self._db.list_bg_jobs(status="running")
        recovered = 0
        for job in jobs:
            logger.info("Recovering job: %s (%s)", job["id"], job["title"])
            from breadmind.tasks.celery_app import celery_app
            if job.get("job_type") == "monitor":
                task = celery_app.send_task(
                    "breadmind.execute_monitor_job", args=[str(job["id"])],
                )
            else:
                task = celery_app.send_task(
                    "breadmind.execute_bg_job", args=[str(job["id"])],
                )
            await self._db.update_bg_job_status(
                str(job["id"]), "running", celery_task_id=task.id,
            )
            recovered += 1
        if recovered:
            logger.info("Recovered %d background jobs", recovered)

    async def cleanup_old_jobs(self, retention_days: int = 30):
        await self._db.cleanup_old_bg_jobs(retention_days)
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/tasks/manager.py
git commit -m "feat(tasks): add BackgroundJobManager with lifecycle control"
```

### Task 6: Create REST API routes

**Files:**
- Create: `src/breadmind/web/routes/bg_jobs.py`

- [ ] **Step 1: Create bg_jobs.py**

```python
"""Background job REST API routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from breadmind.web.dependencies import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bg-jobs"])


def setup_bg_job_routes(r, app_state):
    """Register background job routes."""

    @r.get("/api/bg-jobs")
    async def list_jobs(status: str | None = None, request: Request = None):
        mgr = getattr(app_state, "_bg_job_manager", None)
        if not mgr:
            return JSONResponse(status_code=503, content={"error": "Background jobs not available"})
        jobs = await mgr.list_jobs(status=status)
        # Serialize UUIDs and timestamps
        for j in jobs:
            for k, v in j.items():
                if hasattr(v, "isoformat"):
                    j[k] = v.isoformat()
                elif hasattr(v, "hex"):
                    j[k] = str(v)
        return {"jobs": jobs}

    @r.get("/api/bg-jobs/{job_id}")
    async def get_job(job_id: str):
        mgr = getattr(app_state, "_bg_job_manager", None)
        if not mgr:
            return JSONResponse(status_code=503, content={"error": "Background jobs not available"})
        job = await mgr.get_job(job_id)
        if not job:
            return JSONResponse(status_code=404, content={"error": "Job not found"})
        for k, v in job.items():
            if hasattr(v, "isoformat"):
                job[k] = v.isoformat()
            elif hasattr(v, "hex"):
                job[k] = str(v)
        return {"job": job}

    @r.post("/api/bg-jobs/{job_id}/pause")
    async def pause_job(job_id: str):
        mgr = getattr(app_state, "_bg_job_manager", None)
        if not mgr:
            return JSONResponse(status_code=503, content={"error": "Background jobs not available"})
        ok = await mgr.pause_job(job_id)
        if not ok:
            return JSONResponse(status_code=400, content={"error": "Cannot pause this job"})
        return {"success": True}

    @r.post("/api/bg-jobs/{job_id}/resume")
    async def resume_job(job_id: str):
        mgr = getattr(app_state, "_bg_job_manager", None)
        if not mgr:
            return JSONResponse(status_code=503, content={"error": "Background jobs not available"})
        ok = await mgr.resume_job(job_id)
        if not ok:
            return JSONResponse(status_code=400, content={"error": "Cannot resume this job"})
        return {"success": True}

    @r.post("/api/bg-jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        mgr = getattr(app_state, "_bg_job_manager", None)
        if not mgr:
            return JSONResponse(status_code=503, content={"error": "Background jobs not available"})
        ok = await mgr.cancel_job(job_id)
        if not ok:
            return JSONResponse(status_code=400, content={"error": "Cannot cancel this job"})
        return {"success": True}

    @r.delete("/api/bg-jobs/{job_id}")
    async def delete_job(job_id: str):
        mgr = getattr(app_state, "_bg_job_manager", None)
        if not mgr:
            return JSONResponse(status_code=503, content={"error": "Background jobs not available"})
        ok = await mgr.delete_job(job_id)
        if not ok:
            return JSONResponse(status_code=400, content={"error": "Cannot delete this job"})
        return {"success": True}
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/web/routes/bg_jobs.py
git commit -m "feat(web): add bg-jobs REST API routes"
```

---

## Chunk 4: Integration (builtin tool, bootstrap, app)

### Task 7: Add run_background builtin tool

**Files:**
- Modify: `src/breadmind/tools/builtin.py`

- [ ] **Step 1: Add run_background tool function**

Add before `register_builtin_tools()`:

```python
@tool(
    name="run_background",
    description=(
        "Start a long-running background job. Use for tasks that take more than a few minutes. "
        "Provide a title, job_type ('single' or 'monitor'), steps (list of descriptions), "
        "and tools_needed (list of tool names). For monitors, provide monitor_config."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Job title"},
            "job_type": {"type": "string", "enum": ["single", "monitor"], "description": "Job type"},
            "steps": {"type": "array", "items": {"type": "string"}, "description": "Step descriptions (single type)"},
            "tools_needed": {"type": "array", "items": {"type": "string"}, "description": "Tools to use"},
            "monitor_config": {"type": "object", "description": "Monitor configuration (monitor type)"},
        },
        "required": ["title", "job_type"],
    },
)
async def run_background(title, job_type="single", steps=None, tools_needed=None, monitor_config=None, **kwargs):
    """Create and dispatch a background job."""
    from breadmind.tasks.manager import BackgroundJobManager

    # Access manager via global registry metadata
    mgr = _bg_job_manager
    if not mgr:
        return "Background job system not available. Ensure Redis and Celery are configured."

    # Build execution plan from steps
    execution_plan = []
    if job_type == "single" and steps:
        for i, desc in enumerate(steps):
            tool_name = (tools_needed[i] if tools_needed and i < len(tools_needed)
                         else tools_needed[0] if tools_needed else "shell_exec")
            execution_plan.append({
                "step": i + 1,
                "description": desc,
                "tool": tool_name,
                "args": {},  # Worker will need to interpret
            })

    metadata = {}
    if monitor_config:
        metadata["monitor_config"] = monitor_config

    try:
        result = await mgr.create_job(
            title=title,
            description=f"Background job: {title}",
            job_type=job_type,
            execution_plan=execution_plan,
            metadata=metadata,
        )
        return f"Background job '{title}' started (ID: {result['job_id']}). Check progress at /api/bg-jobs/{result['job_id']}"
    except ValueError as e:
        return f"Failed to create background job: {e}"
    except Exception as e:
        return f"Background job system error: {e}"


# Module-level reference for DI
_bg_job_manager = None

def set_bg_job_manager(mgr):
    global _bg_job_manager
    _bg_job_manager = mgr
```

- [ ] **Step 2: Register in register_builtin_tools()**

```python
def register_builtin_tools(registry) -> None:
    for t in [shell_exec, web_search, file_read, file_write, messenger_connect,
              swarm_role, delegate_tasks, network_scan, router_manage, run_background]:
        registry.register(t)
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/tools/builtin.py
git commit -m "feat(tools): add run_background builtin tool"
```

### Task 8: Bootstrap integration

**Files:**
- Modify: `src/breadmind/core/bootstrap.py`
- Modify: `src/breadmind/web/app.py`

- [ ] **Step 1: Add BackgroundJobManager init to bootstrap.py**

Add a new `init_bg_jobs()` function:

```python
async def init_bg_jobs(db, config):
    """Initialize background job manager. Requires PostgreSQL + Redis."""
    if db is None or not hasattr(db, "create_bg_job"):
        logger.warning("Background jobs disabled: PostgreSQL required")
        return None

    from breadmind.tasks.manager import BackgroundJobManager
    redis_url = getattr(config, "task", None)
    redis_url = redis_url.redis_url if redis_url else "redis://localhost:6379/0"
    max_monitors = redis_url.max_concurrent_monitors if hasattr(redis_url, "max_concurrent_monitors") else 10

    mgr = BackgroundJobManager(db, redis_url=redis_url, max_monitors=max_monitors)

    # Recover interrupted jobs
    try:
        await mgr.recover_on_startup()
    except Exception:
        logger.warning("Background job recovery failed", exc_info=True)

    # Cleanup old jobs
    try:
        retention = config.task.completed_retention_days if hasattr(config, "task") else 30
        await mgr.cleanup_old_jobs(retention)
    except Exception:
        logger.warning("Background job cleanup failed", exc_info=True)

    # Wire to builtin tools
    from breadmind.tools.builtin import set_bg_job_manager
    set_bg_job_manager(mgr)

    logger.info("Background job manager initialized")
    return mgr
```

- [ ] **Step 2: Register bg_jobs routes in app.py**

Add import and route registration:

```python
from breadmind.web.routes.bg_jobs import setup_bg_job_routes
# In _setup_routes():
setup_bg_job_routes(app, self)
```

Add `bg_job_manager` parameter to `WebApp.__init__()` and store as `self._bg_job_manager`.

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/core/bootstrap.py src/breadmind/web/app.py
git commit -m "feat: integrate BackgroundJobManager into bootstrap and web app"
```

### Task 9: Redis Pub/Sub listener for WebSocket broadcast

**Files:**
- Modify: `src/breadmind/web/app.py`

- [ ] **Step 1: Add Redis subscription startup task**

In `WebApp.__init__()`, add a startup event:

```python
@self.app.on_event("startup")
async def _start_redis_bg_listener():
    if not self._bg_job_manager:
        return
    import asyncio
    asyncio.create_task(self._redis_bg_job_listener())
```

Add the listener method:

```python
async def _redis_bg_job_listener(self):
    """Subscribe to Redis Pub/Sub for background job updates."""
    try:
        import aioredis
        redis_url = os.environ.get("BREADMIND_REDIS_URL", "redis://localhost:6379/0")
        redis = aioredis.from_url(redis_url)
        pubsub = redis.pubsub()
        await pubsub.psubscribe("breadmind:bg_job:*")
        async for msg in pubsub.listen():
            if msg.get("type") == "pmessage" and msg.get("data"):
                try:
                    data = json.loads(msg["data"])
                    await self.broadcast_event({"type": "bg_job_update", **data})
                except Exception:
                    pass
    except Exception:
        logger.warning("Redis Pub/Sub listener not available", exc_info=True)
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/web/app.py
git commit -m "feat(web): add Redis Pub/Sub listener for bg-job WebSocket broadcast"
```

---

## Chunk 5: Dependencies and Testing

### Task 10: Add Python dependencies

- [ ] **Step 1: Install required packages**

```bash
pip install celery redis aioredis gevent
```

- [ ] **Step 2: Add to pyproject.toml or requirements**

Add `celery`, `redis`, `aioredis`, `gevent` to the project dependencies.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add celery, redis, aioredis, gevent dependencies"
```

### Task 11: Manual integration test

- [ ] **Step 1: Verify Redis is running**

```bash
redis-cli ping
# Expected: PONG
```

- [ ] **Step 2: Start Celery worker**

```bash
celery -A breadmind.tasks.celery_app worker --pool=gevent --loglevel=info
```

- [ ] **Step 3: Start BreadMind server**

```bash
python -m breadmind.main --web
```

- [ ] **Step 4: Test via API**

```bash
# Create a test job
curl -X POST http://localhost:8080/api/bg-jobs -H "Content-Type: application/json" \
  -d '{"title": "Test Job", "job_type": "single", "steps": ["ping localhost"]}'

# List jobs
curl http://localhost:8080/api/bg-jobs

# Check job status
curl http://localhost:8080/api/bg-jobs/{job_id}
```

- [ ] **Step 5: Test pause/resume/cancel**

```bash
curl -X POST http://localhost:8080/api/bg-jobs/{job_id}/pause
curl -X POST http://localhost:8080/api/bg-jobs/{job_id}/resume
curl -X POST http://localhost:8080/api/bg-jobs/{job_id}/cancel
```
