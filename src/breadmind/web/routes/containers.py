"""Container routes: Docker container management."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from breadmind.web.dependencies import get_container_executor

logger = logging.getLogger(__name__)


def setup_container_routes(r: APIRouter, app_state):
    """Register container management routes."""

    @r.get("/api/container/status")
    async def container_status(executor=Depends(get_container_executor)):
        if not executor:
            return {"status": {"docker_available": False, "running_containers": 0, "containers": []}}
        return {"status": executor.get_status()}

    @r.get("/api/container/list")
    async def container_list(executor=Depends(get_container_executor)):
        if not executor:
            return {"containers": []}
        return {"containers": executor.list_containers()}

    @r.post("/api/container/run")
    async def container_run(request: Request, executor=Depends(get_container_executor)):
        if not executor:
            return JSONResponse(status_code=503, content={"error": "Container executor not configured"})
        data = await request.json()
        result = await executor.run_command(
            command=data.get("command", ""),
            image=data.get("image"),
            timeout=data.get("timeout", 30),
            env=data.get("env"),
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "container_id": result.container_id,
            "error": result.error,
        }

    @r.post("/api/container/cleanup")
    async def container_cleanup(executor=Depends(get_container_executor)):
        if not executor:
            return JSONResponse(status_code=503, content={"error": "Container executor not configured"})
        await executor.cleanup()
        return {"status": "ok"}
