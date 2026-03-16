"""Worker provisioning and monitoring routes."""
from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workers"])


def setup_worker_routes(r: APIRouter, app_state):
    """Register /api/workers/* routes."""

    # ── Token Management ──

    @r.post("/api/workers/tokens")
    async def create_token(
        ttl_hours: float = 1,
        max_uses: int = 1,
        labels: str = "",
    ):
        """Create a new join token for worker registration."""
        token_mgr = getattr(app_state, '_token_manager', None)
        if not token_mgr:
            return JSONResponse(status_code=503, content={"error": "Token manager not available"})

        parsed_labels = {}
        if labels:
            try:
                parsed_labels = json.loads(labels)
            except json.JSONDecodeError:
                parsed_labels = {"role": labels}

        token = token_mgr.create_token(
            ttl_hours=ttl_hours,
            max_uses=max_uses,
            created_by="api",
            labels=parsed_labels,
        )

        # Build one-liner install command (single URL, OS auto-detected)
        commander_url = _get_commander_ws_url(app_state)
        base_url = _get_base_url(app_state)
        script_url = f'{base_url}/api/workers/install-script?token={token.secret}'

        return {
            "token": token.to_dict(),
            "install_url": script_url,
            "install_commands": {
                "linux": f'curl -fsSL {script_url} | bash',
                "windows": f'irm {script_url} | iex',
            },
            "commander_url": commander_url,
        }

    @r.get("/api/workers/tokens")
    async def list_tokens():
        """List active join tokens."""
        token_mgr = getattr(app_state, '_token_manager', None)
        if not token_mgr:
            return {"tokens": []}
        return {"tokens": token_mgr.list_tokens()}

    @r.delete("/api/workers/tokens/{token_id}")
    async def revoke_token(token_id: str):
        """Revoke a join token."""
        token_mgr = getattr(app_state, '_token_manager', None)
        if not token_mgr:
            return JSONResponse(status_code=503, content={"error": "Token manager not available"})
        if token_mgr.revoke(token_id):
            return {"status": "revoked", "token_id": token_id}
        return JSONResponse(status_code=404, content={"error": "Token not found"})

    # ── Install Script ──

    @r.get("/api/workers/install-script")
    async def install_script(request: Request, token: str, os: str = ""):
        """Generate and serve a dynamic install script.

        OS is auto-detected from User-Agent:
        - PowerShell → windows script
        - curl/wget/anything else → linux/bash script
        Explicit ?os=windows overrides auto-detection.
        """
        token_mgr = getattr(app_state, '_token_manager', None)
        if not token_mgr:
            return PlainTextResponse("# Error: Token manager not available", status_code=503)

        # Validate token without consuming
        tk = token_mgr.peek(token)
        if not tk:
            return PlainTextResponse("# Error: Invalid or expired token", status_code=403)

        # Auto-detect OS from User-Agent if not explicitly provided
        os_type = os
        if not os_type:
            ua = (request.headers.get("user-agent") or "").lower()
            if "powershell" in ua or "windowspowershell" in ua:
                os_type = "windows"
            else:
                os_type = "linux"

        from breadmind.network.install_generator import generate_install_script
        commander_url = _get_commander_ws_url(app_state)

        script = generate_install_script(
            commander_url=commander_url,
            token_secret=token,
            os_type=os_type,
        )

        return PlainTextResponse(script, media_type="text/plain")

    # ── SSH Push Deploy ──

    @r.post("/api/workers/deploy")
    async def deploy_via_ssh(
        host: str,
        username: str = "root",
        port: int = 22,
        password: str = "",
        key_file: str = "",
        agent_id: str = "",
    ):
        """Deploy a worker to a remote host via SSH."""
        token_mgr = getattr(app_state, '_token_manager', None)
        if not token_mgr:
            return JSONResponse(status_code=503, content={"error": "Token manager not available"})

        # Create a one-time token
        token = token_mgr.create_token(
            ttl_hours=0.5,  # 30 min for SSH deploy
            max_uses=1,
            created_by=f"ssh-deploy:{host}",
            labels={"deployed_via": "ssh", "host": host},
        )

        commander_url = _get_commander_ws_url(app_state)
        base_url = _get_base_url(app_state)

        from breadmind.network.install_generator import generate_install_script
        script = generate_install_script(
            commander_url=commander_url,
            token_secret=token.secret,
            agent_id=agent_id or f"worker-{host.replace('.', '-')}",
            os_type="linux",
        )

        # Execute via SSH
        try:
            import asyncssh

            connect_kwargs = {
                "host": host,
                "port": port,
                "username": username,
                "known_hosts": None,
            }
            if password:
                connect_kwargs["password"] = password
            if key_file:
                connect_kwargs["client_keys"] = [key_file]

            async with asyncssh.connect(**connect_kwargs) as conn:
                result = await asyncio.wait_for(
                    conn.run(f'bash -c "{_escape_for_ssh(script)}"' if len(script) < 8000
                             else f'cat << \'BREADMIND_EOF\' | bash\n{script}\nBREADMIND_EOF'),
                    timeout=300,
                )

                return {
                    "status": "deployed" if result.exit_status == 0 else "failed",
                    "host": host,
                    "agent_id": agent_id or f"worker-{host.replace('.', '-')}",
                    "token_id": token.token_id,
                    "exit_code": result.exit_status,
                    "stdout": (result.stdout or "")[:2000],
                    "stderr": (result.stderr or "")[:1000],
                }

        except ImportError:
            return JSONResponse(
                status_code=500,
                content={"error": "asyncssh not installed. Run: pip install asyncssh"},
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"SSH deployment failed: {e}", "host": host},
            )

    # ── Worker Monitoring ──

    @r.get("/api/workers")
    async def list_workers():
        """List all registered workers with status and metrics."""
        commander = getattr(app_state, '_commander', None)
        if not commander:
            return {"workers": []}

        registry = commander._registry
        agents = registry.list_all()
        workers = []
        for agent in agents:
            info = {
                "agent_id": agent.agent_id,
                "status": agent.status.value if hasattr(agent.status, 'value') else str(agent.status),
                "host": agent.host,
                "environment": agent.environment,
                "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
                "roles": [r.name for r in agent.roles] if agent.roles else [],
                "metrics": agent.metrics if hasattr(agent, 'metrics') else {},
            }
            workers.append(info)

        return {"workers": workers}

    @r.get("/api/workers/{agent_id}")
    async def get_worker(agent_id: str):
        """Get detailed worker info including env scan and task history."""
        commander = getattr(app_state, '_commander', None)
        if not commander:
            return JSONResponse(status_code=404, content={"error": "Commander not available"})

        agent = commander._registry.get(agent_id)
        if not agent:
            return JSONResponse(status_code=404, content={"error": f"Worker not found: {agent_id}"})

        # Task history from completed_tasks
        tasks = [
            {"task_id": tid, **result}
            for tid, result in commander.completed_tasks.items()
            if result.get("agent_id") == agent_id
        ]

        return {
            "agent_id": agent.agent_id,
            "status": agent.status.value if hasattr(agent.status, 'value') else str(agent.status),
            "host": agent.host,
            "environment": agent.environment,
            "last_heartbeat": agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
            "roles": [{"name": r.name, "tools": r.tools} for r in agent.roles] if agent.roles else [],
            "metrics": agent.metrics if hasattr(agent, 'metrics') else {},
            "cert_fingerprint": agent.cert_fingerprint if hasattr(agent, 'cert_fingerprint') else "",
            "recent_tasks": tasks[-20:],
        }

    @r.post("/api/workers/{agent_id}/command")
    async def send_worker_command(agent_id: str, command: str = "restart"):
        """Send a command to a worker (restart, decommission)."""
        commander = getattr(app_state, '_commander', None)
        if not commander:
            return JSONResponse(status_code=503, content={"error": "Commander not available"})

        try:
            await commander.send_command(agent_id, command)
            return {"status": "sent", "agent_id": agent_id, "command": command}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @r.delete("/api/workers/{agent_id}")
    async def remove_worker(agent_id: str):
        """Decommission and remove a worker."""
        commander = getattr(app_state, '_commander', None)
        if not commander:
            return JSONResponse(status_code=503, content={"error": "Commander not available"})

        try:
            await commander.send_command(agent_id, "decommission")
            commander._registry.set_status(agent_id, "REMOVED")
            return {"status": "removed", "agent_id": agent_id}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})


def _get_commander_ws_url(app_state) -> str:
    """Build the Commander WebSocket URL."""
    config = getattr(app_state, '_config', None)
    if config and hasattr(config, 'network'):
        if config.network.commander_url:
            return config.network.commander_url
    host = getattr(app_state, '_host', "localhost")
    port = getattr(app_state, '_ws_port', 8081)
    return f"ws://{host}:{port}/ws/agent"


def _get_base_url(app_state) -> str:
    """Build the Commander HTTP base URL."""
    config = getattr(app_state, '_config', None)
    host = "localhost"
    port = 8080
    if config:
        host = getattr(config.web, 'host', 'localhost')
        port = getattr(config.web, 'port', 8080)
    if host in ("0.0.0.0", ""):
        import socket
        try:
            host = socket.gethostbyname(socket.gethostname())
        except Exception:
            host = "localhost"
    return f"http://{host}:{port}"


def _escape_for_ssh(script: str) -> str:
    """Escape script for inline SSH execution."""
    return script.replace("'", "'\\''").replace('"', '\\"')
