"""Sub-agent routes: spawn and manage sub-agent tasks."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def setup_subagent_routes(r: APIRouter, app_state):
    """Register sub-agent management routes."""

    @r.post("/api/subagent/spawn")
    async def spawn_subagent(request: Request):
        if not app_state._subagent_manager:
            return JSONResponse(status_code=503, content={"error": "Sub-agent manager not configured"})
        data = await request.json()
        task = await app_state._subagent_manager.spawn(
            task=data.get("task", ""),
            parent_id=data.get("parent_id"),
            model=data.get("model"),
        )
        return {"status": "ok", "task_id": task.id}

    @r.get("/api/subagent/tasks")
    async def list_subagent_tasks():
        if not app_state._subagent_manager:
            return {"tasks": []}
        return {"tasks": app_state._subagent_manager.list_tasks()}

    @r.get("/api/subagent/tasks/{task_id}")
    async def get_subagent_task(task_id: str):
        if not app_state._subagent_manager:
            return JSONResponse(status_code=503, content={"error": "Sub-agent manager not configured"})
        task = app_state._subagent_manager.get_task(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})
        return {"task": task}

    @r.get("/api/subagent/status")
    async def subagent_status():
        if not app_state._subagent_manager:
            return {"status": {"total": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0}}
        return {"status": app_state._subagent_manager.get_status()}
