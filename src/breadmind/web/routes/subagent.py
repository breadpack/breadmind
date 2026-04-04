"""Orchestrator API routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/orchestrator/status")
async def orchestrator_status(request: Request):
    """Return orchestrator availability status."""
    app_state = getattr(request.app.state, "app_state", None)
    if not app_state:
        return JSONResponse({"available": False})
    orchestrator = getattr(app_state, "_orchestrator", None)
    return JSONResponse({"available": orchestrator is not None})


@router.get("/api/orchestrator/roles")
async def list_roles(request: Request):
    """List all available subagent roles."""
    app_state = getattr(request.app.state, "app_state", None)
    if not app_state:
        return JSONResponse({"roles": []})
    role_registry = getattr(app_state, "_role_registry", None)
    if role_registry is None:
        return JSONResponse({"roles": []})
    roles = [
        {
            "name": r.name,
            "domain": r.domain,
            "task_type": r.task_type,
            "description": r.description,
            "dedicated_tools": r.dedicated_tools,
        }
        for r in role_registry.list_roles()
    ]
    return JSONResponse({"roles": roles})


def setup_subagent_routes(app, app_state):
    """Register sub-agent routes."""
    app.include_router(router)
