"""Messenger routes: auto-connect wizard, lifecycle, security."""
from __future__ import annotations

import logging
import os
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)


def _wizard_state_to_dict(state) -> dict:
    result = {
        "session_id": state.session_id,
        "platform": state.platform,
        "current_step": state.current_step,
        "total_steps": state.total_steps,
        "status": state.status,
        "message": state.message,
        "error": state.error,
    }
    if state.step_info:
        result["step_info"] = {
            "step_number": state.step_info.step_number,
            "title": state.step_info.title,
            "description": state.step_info.description,
            "action_type": state.step_info.action_type,
            "action_url": state.step_info.action_url,
            "auto_executable": state.step_info.auto_executable,
        }
        if state.step_info.input_fields:
            result["step_info"]["input_fields"] = [
                {
                    "name": f.name,
                    "label": f.label,
                    "placeholder": f.placeholder,
                    "secret": f.secret,
                    "required": f.required,
                }
                for f in state.step_info.input_fields
            ]
    return result


def setup_messenger_routes(app, app_state):
    """Register messenger auto-connect, lifecycle, and security routes."""

    # ── Auto-Connect Wizard Routes ──

    @app.post("/api/messenger/{platform}/auto-connect")
    async def messenger_auto_connect(platform: str, request: Request):
        orchestrator = app_state._orchestrator
        if not orchestrator:
            return JSONResponse({"error": "Orchestrator not initialized"}, 500)
        state = await orchestrator.start_connection(platform, "web")
        return _wizard_state_to_dict(state)

    @app.post("/api/messenger/wizard/{session_id}/step")
    async def messenger_wizard_step(session_id: str, request: Request):
        orchestrator = app_state._orchestrator
        if not orchestrator:
            return JSONResponse({"error": "Orchestrator not initialized"}, 500)
        body = await request.json()
        state = await orchestrator.process_step(session_id, body)
        return _wizard_state_to_dict(state)

    @app.get("/api/messenger/wizard/{session_id}/status")
    async def messenger_wizard_status(session_id: str):
        orchestrator = app_state._orchestrator
        if not orchestrator:
            return JSONResponse({"error": "Orchestrator not initialized"}, 500)
        state = orchestrator.get_current_state(session_id)
        if not state:
            return JSONResponse({"error": "Session not found"}, 404)
        return _wizard_state_to_dict(state)

    @app.delete("/api/messenger/wizard/{session_id}")
    async def messenger_wizard_cancel(session_id: str):
        orchestrator = app_state._orchestrator
        if not orchestrator:
            return JSONResponse({"error": "Orchestrator not initialized"}, 500)
        await orchestrator.cancel(session_id)
        return {"status": "cancelled"}

    # ── Lifecycle Routes ──

    @app.get("/api/messenger/lifecycle/status")
    async def messenger_lifecycle_status():
        lifecycle = app_state._lifecycle_manager
        if not lifecycle:
            return JSONResponse({"error": "Lifecycle manager not initialized"}, 500)
        statuses = lifecycle.get_all_statuses()
        return {
            platform: {
                "state": s.state.value,
                "retry_count": s.retry_count,
                "last_error": s.last_error,
            }
            for platform, s in statuses.items()
        }

    @app.post("/api/messenger/lifecycle/{platform}/restart")
    async def messenger_lifecycle_restart(platform: str):
        lifecycle = app_state._lifecycle_manager
        if not lifecycle:
            return JSONResponse({"error": "Lifecycle manager not initialized"}, 500)
        success = await lifecycle.restart_gateway(platform)
        return {"platform": platform, "restarted": success}

    @app.get("/api/messenger/lifecycle/health")
    async def messenger_lifecycle_health():
        lifecycle = app_state._lifecycle_manager
        if not lifecycle:
            return JSONResponse({"error": "Lifecycle manager not initialized"}, 500)
        health = await lifecycle.health_check_all()
        return {
            platform: {
                "state": h.state.value,
                "error": h.error,
                "retry_count": h.retry_count,
                "uptime_seconds": h.uptime_seconds,
            }
            for platform, h in health.items()
        }

    # ── Security Routes ──

    @app.get("/api/messenger/security/logs")
    async def messenger_security_logs(platform: str = None, limit: int = 50):
        security = app_state._messenger_security
        if not security:
            return JSONResponse({"error": "Security manager not initialized"}, 500)
        logs = security.get_access_logs(platform, limit)
        return [
            {
                "timestamp": log.timestamp,
                "platform": log.platform,
                "action": log.action,
                "actor": log.actor,
            }
            for log in logs
        ]

    @app.get("/api/messenger/security/{platform}/expiry")
    async def messenger_security_expiry(platform: str):
        security = app_state._messenger_security
        if not security:
            return JSONResponse({"error": "Security manager not initialized"}, 500)
        status = await security.check_token_expiry(platform)
        return {
            "platform": status.platform,
            "token_type": status.token_type,
            "needs_rotation": status.needs_rotation,
        }
