"""Tool listing and approval routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tools"])


def setup_tools_routes(r: APIRouter, app_state):
    """Register /api/tools and /api/approvals/* routes."""

    @r.get("/api/tools")
    async def list_tools():
        if app_state._tool_registry:
            defs = app_state._tool_registry.get_all_definitions()
            return {"tools": [
                {"name": d.name, "description": d.description, "source": app_state._tool_registry.get_tool_source(d.name)}
                for d in defs
            ]}
        return {"tools": []}

    @r.get("/api/approvals")
    async def get_approvals():
        """Return pending approval requests."""
        if app_state._agent and hasattr(app_state._agent, 'get_pending_approvals'):
            return {"approvals": app_state._agent.get_pending_approvals()}
        return {"approvals": []}

    @r.post("/api/approvals/{approval_id}/approve")
    async def approve_tool(approval_id: str):
        """Approve and execute a pending tool, then resume LLM conversation."""
        import asyncio
        if not app_state._agent or not hasattr(app_state._agent, 'approve_tool'):
            return JSONResponse(
                status_code=404,
                content={"error": "Approval not found or agent not configured"},
            )
        result = app_state._agent.approve_tool(approval_id)
        if asyncio.iscoroutine(result):
            result = await result
        # Resume LLM conversation with the tool result
        followup = None
        if hasattr(result, 'success') and result.success:
            if hasattr(app_state._agent, 'resume_after_approval'):
                followup = app_state._agent.resume_after_approval(approval_id, result)
                if asyncio.iscoroutine(followup):
                    followup = await followup
            return {
                "status": "approved",
                "approval_id": approval_id,
                "result": {"success": result.success, "output": result.output[:1000] if result.output else ""},
                "followup": followup,
            }
        return {
            "status": "approved",
            "approval_id": approval_id,
            "result": result if isinstance(result, dict) else {"success": bool(result)},
        }

    @r.post("/api/approvals/{approval_id}/deny")
    async def deny_tool(approval_id: str):
        """Deny a pending tool execution."""
        if not app_state._agent or not hasattr(app_state._agent, 'deny_tool'):
            return JSONResponse(
                status_code=404,
                content={"error": "Approval not found or agent not configured"},
            )
        app_state._agent.deny_tool(approval_id)
        return {"status": "denied", "approval_id": approval_id}
