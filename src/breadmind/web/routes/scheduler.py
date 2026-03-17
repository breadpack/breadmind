"""Scheduler routes: cron jobs and heartbeat tasks."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from breadmind.web.dependencies import get_db, get_scheduler

logger = logging.getLogger(__name__)


def setup_scheduler_routes(r: APIRouter, app_state):
    """Register scheduler-related routes."""

    @r.get("/api/scheduler/status")
    async def scheduler_status(scheduler=Depends(get_scheduler)):
        if not scheduler:
            return {"status": {"running": False, "cron_jobs": 0, "heartbeats": 0, "total_runs": 0}}
        return {"status": scheduler.get_status()}

    @r.get("/api/scheduler/cron")
    async def list_cron_jobs(scheduler=Depends(get_scheduler)):
        if not scheduler:
            return {"jobs": []}
        return {"jobs": scheduler.get_cron_jobs()}

    @r.post("/api/scheduler/cron")
    async def add_cron_job(request: Request, scheduler=Depends(get_scheduler), db=Depends(get_db)):
        if not scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        data = await request.json()
        import uuid
        job_id = data.get("id", str(uuid.uuid4())[:8])
        from breadmind.core.scheduler import CronJob
        job = CronJob(
            id=job_id, name=data.get("name", ""), schedule=data.get("schedule", ""),
            task=data.get("task", ""), enabled=data.get("enabled", True),
            model=data.get("model"),
        )
        scheduler.add_cron_job(job)
        # Persist to DB
        if db:
            try:
                jobs = scheduler.get_cron_jobs()
                await db.set_setting("scheduler_cron", jobs)
            except Exception:
                pass
        return {"status": "ok", "job": {"id": job_id, "name": job.name}}

    @r.delete("/api/scheduler/cron/{job_id}")
    async def delete_cron_job(job_id: str, scheduler=Depends(get_scheduler), db=Depends(get_db)):
        if not scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        removed = scheduler.remove_cron_job(job_id)
        if db:
            try:
                await db.set_setting("scheduler_cron", scheduler.get_cron_jobs())
            except Exception:
                pass
        return {"status": "ok" if removed else "not_found"}

    @r.get("/api/scheduler/heartbeat")
    async def list_heartbeats(scheduler=Depends(get_scheduler)):
        if not scheduler:
            return {"heartbeats": []}
        return {"heartbeats": scheduler.get_heartbeats()}

    @r.post("/api/scheduler/heartbeat")
    async def add_heartbeat(request: Request, scheduler=Depends(get_scheduler), db=Depends(get_db)):
        if not scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        data = await request.json()
        import uuid
        hb_id = data.get("id", str(uuid.uuid4())[:8])
        from breadmind.core.scheduler import HeartbeatTask
        hb = HeartbeatTask(
            id=hb_id, name=data.get("name", ""), interval_minutes=data.get("interval_minutes", 30),
            task=data.get("task", ""), enabled=data.get("enabled", True),
        )
        scheduler.add_heartbeat(hb)
        if db:
            try:
                await db.set_setting("scheduler_heartbeat", scheduler.get_heartbeats())
            except Exception:
                pass
        return {"status": "ok", "heartbeat": {"id": hb_id, "name": hb.name}}

    @r.delete("/api/scheduler/heartbeat/{hb_id}")
    async def delete_heartbeat(hb_id: str, scheduler=Depends(get_scheduler), db=Depends(get_db)):
        if not scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        removed = scheduler.remove_heartbeat(hb_id)
        if db:
            try:
                await db.set_setting("scheduler_heartbeat", scheduler.get_heartbeats())
            except Exception:
                pass
        return {"status": "ok" if removed else "not_found"}
