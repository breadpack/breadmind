"""Companion device management routes."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse

from breadmind.web.dependencies import get_app_state, get_commander, get_token_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["companions"])


def setup_companion_routes(r: APIRouter, app_state) -> None:
    """Register /api/companions/* routes."""

    @r.get("/api/companions")
    async def list_companions(commander=Depends(get_commander)):
        """List all companion devices."""
        if not commander:
            return {"companions": []}

        companions = commander._registry.list_companions()
        result = []
        for agent in companions:
            result.append({
                "agent_id": agent.agent_id,
                "status": agent.status.value if hasattr(agent.status, "value") else str(agent.status),
                "host": agent.host,
                "device_name": agent.environment.get("device_name", ""),
                "os": agent.environment.get("os", ""),
                "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
                "metrics": agent.last_metrics,
                "capabilities": agent.environment.get("capabilities", []),
            })
        return {"companions": result}

    @r.get("/api/companions/{agent_id}")
    async def get_companion(agent_id: str, commander=Depends(get_commander)):
        """Get detailed companion info."""
        if not commander:
            return JSONResponse(status_code=503, content={"error": "Commander not available"})

        agent = commander._registry.get(agent_id)
        if not agent or agent.environment.get("agent_type") != "companion":
            return JSONResponse(status_code=404, content={"error": f"Companion not found: {agent_id}"})

        return {
            "agent_id": agent.agent_id,
            "status": agent.status.value if hasattr(agent.status, "value") else str(agent.status),
            "host": agent.host,
            "device_name": agent.environment.get("device_name", ""),
            "os": agent.environment.get("os", ""),
            "os_version": agent.environment.get("os_version", ""),
            "architecture": agent.environment.get("architecture", ""),
            "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
            "metrics": agent.last_metrics,
            "capabilities": agent.environment.get("capabilities", []),
            "environment": agent.environment,
        }

    @r.post("/api/companions/pair")
    async def pair_companion(
        token_mgr=Depends(get_token_manager),
        app=Depends(get_app_state),
    ):
        """Generate a pairing token and URL for a new companion."""
        if not token_mgr:
            return JSONResponse(status_code=503, content={"error": "Token manager not available"})

        token = token_mgr.create_token(
            ttl_hours=0.5,
            max_uses=1,
            created_by="companion-pairing",
            labels={"type": "companion"},
        )

        from breadmind.web.routes.workers import _get_commander_ws_url, _get_base_url
        from breadmind.companion.pairing import generate_pairing_url

        commander_url = _get_commander_ws_url(app)
        pairing_url = generate_pairing_url(commander_url, token.secret)
        base_url = _get_base_url(app)

        return {
            "token": token.to_dict(),
            "commander_url": commander_url,
            "pairing_url": pairing_url,
            "install_script_url": f"{base_url}/api/companions/install-script?token={token.secret}",
        }

    @r.delete("/api/companions/{agent_id}")
    async def unpair_companion(agent_id: str, commander=Depends(get_commander)):
        """Unpair and remove a companion device."""
        if not commander:
            return JSONResponse(status_code=503, content={"error": "Commander not available"})

        agent = commander._registry.get(agent_id)
        if not agent or agent.environment.get("agent_type") != "companion":
            return JSONResponse(status_code=404, content={"error": f"Companion not found: {agent_id}"})

        try:
            await commander.send_command(agent_id, "decommission")
        except Exception:
            pass
        commander._registry.remove(agent_id)
        return {"status": "unpaired", "agent_id": agent_id}

    @r.post("/api/companions/{agent_id}/task")
    async def send_companion_task(
        agent_id: str,
        tool: str = "",
        arguments: str = "{}",
        commander=Depends(get_commander),
    ):
        """Send a task to a companion device."""
        if not commander:
            return JSONResponse(status_code=503, content={"error": "Commander not available"})

        agent = commander._registry.get(agent_id)
        if not agent or agent.environment.get("agent_type") != "companion":
            return JSONResponse(status_code=404, content={"error": f"Companion not found: {agent_id}"})

        import json
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            args = {}

        task_id = await commander.dispatch_task(
            agent_id=agent_id,
            task_type="tool_call",
            params={"tool": tool, "arguments": args},
        )
        return {"task_id": task_id, "agent_id": agent_id, "tool": tool}

    @r.get("/api/companions/{agent_id}/screenshot")
    async def get_companion_screenshot(agent_id: str, commander=Depends(get_commander)):
        """Trigger a screenshot capture on a companion and return the task ID."""
        if not commander:
            return JSONResponse(status_code=503, content={"error": "Commander not available"})

        agent = commander._registry.get(agent_id)
        if not agent or agent.environment.get("agent_type") != "companion":
            return JSONResponse(status_code=404, content={"error": f"Companion not found: {agent_id}"})

        task_id = await commander.dispatch_task(
            agent_id=agent_id,
            task_type="tool_call",
            params={"tool": "companion_screenshot", "arguments": {}},
        )
        return {"task_id": task_id, "agent_id": agent_id}

    @r.get("/api/companions/install-script")
    async def companion_install_script(
        token: str,
        os: str = "linux",
        token_mgr=Depends(get_token_manager),
        app=Depends(get_app_state),
    ):
        """Serve a companion install script."""
        if not token_mgr:
            return PlainTextResponse("# Error: Token manager not available", status_code=503)

        tk = token_mgr.peek(token)
        if not tk:
            return PlainTextResponse("# Error: Invalid or expired token", status_code=403)

        from breadmind.network.install_generator import generate_companion_install_script
        from breadmind.web.routes.workers import _get_commander_ws_url

        commander_url = _get_commander_ws_url(app)
        script = generate_companion_install_script(
            commander_url=commander_url,
            token_secret=token,
            os_type=os,
        )
        return PlainTextResponse(script, media_type="text/plain")
