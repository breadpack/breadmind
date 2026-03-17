"""Worker provisioning and monitoring routes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, JSONResponse

from breadmind.web.dependencies import get_app_state, get_commander, get_token_manager

logger = logging.getLogger(__name__)


def _get_known_hosts() -> str | None:
    """Return the path to known_hosts for SSH host key verification.

    By default, uses ``~/.ssh/known_hosts`` (created if absent).
    Set ``BREADMIND_SSH_STRICT_HOST_KEY=false`` to explicitly disable verification.
    """
    strict = os.environ.get("BREADMIND_SSH_STRICT_HOST_KEY", "true").lower()
    if strict == "false":
        logger.warning(
            "SSH host key verification disabled by BREADMIND_SSH_STRICT_HOST_KEY=false"
        )
        return None
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if not known_hosts.exists():
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        known_hosts.touch(mode=0o644)
    return str(known_hosts)

router = APIRouter(tags=["workers"])


def setup_worker_routes(r: APIRouter, app_state):
    """Register /api/workers/* routes."""

    # ── Token Management ──

    @r.post("/api/workers/tokens")
    async def create_token(
        ttl_hours: float = 1,
        max_uses: int = 1,
        labels: str = "",
        token_mgr=Depends(get_token_manager),
        app=Depends(get_app_state),
    ):
        """Create a new join token for worker registration."""
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
        commander_url = _get_commander_ws_url(app)
        base_url = _get_base_url(app)
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
    async def list_tokens(token_mgr=Depends(get_token_manager)):
        """List active join tokens."""
        if not token_mgr:
            return {"tokens": []}
        return {"tokens": token_mgr.list_tokens()}

    @r.delete("/api/workers/tokens/{token_id}")
    async def revoke_token(token_id: str, token_mgr=Depends(get_token_manager)):
        """Revoke a join token."""
        if not token_mgr:
            return JSONResponse(status_code=503, content={"error": "Token manager not available"})
        if token_mgr.revoke(token_id):
            return {"status": "revoked", "token_id": token_id}
        return JSONResponse(status_code=404, content={"error": "Token not found"})

    # ── Install Script ──

    @r.get("/api/workers/install-script")
    async def install_script(
        request: Request,
        token: str,
        os: str = "",
        token_mgr=Depends(get_token_manager),
        app=Depends(get_app_state),
    ):
        """Generate and serve a dynamic install script.

        OS is auto-detected from User-Agent:
        - PowerShell → windows script
        - curl/wget/anything else → linux/bash script
        Explicit ?os=windows overrides auto-detection.
        """
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
        commander_url = _get_commander_ws_url(app)

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
        token_mgr=Depends(get_token_manager),
        app=Depends(get_app_state),
    ):
        """Deploy a worker to a remote host via SSH."""
        if not token_mgr:
            return JSONResponse(status_code=503, content={"error": "Token manager not available"})

        # Create a one-time token
        token = token_mgr.create_token(
            ttl_hours=0.5,  # 30 min for SSH deploy
            max_uses=1,
            created_by=f"ssh-deploy:{host}",
            labels={"deployed_via": "ssh", "host": host},
        )

        commander_url = _get_commander_ws_url(app)
        base_url = _get_base_url(app)

        from breadmind.network.install_generator import generate_install_script
        script = generate_install_script(
            commander_url=commander_url,
            token_secret=token.secret,
            agent_id=agent_id or f"worker-{host.replace('.', '-')}",
            os_type="linux",
        )

        # Validate HEREDOC delimiter safety
        if "BREADMIND_EOF" in script:
            return JSONResponse(
                status_code=400,
                content={"error": "Script contains forbidden delimiter 'BREADMIND_EOF'"},
            )

        # Execute via SSH
        try:
            import asyncssh

            known_hosts = _get_known_hosts()
            if known_hosts is None:
                logger.warning(
                    "SSH deploy to %s:%d with known_hosts=None — "
                    "host key verification is disabled", host, port,
                )
            connect_kwargs = {
                "host": host,
                "port": port,
                "username": username,
                "known_hosts": known_hosts,
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
    async def list_workers(commander=Depends(get_commander)):
        """List all registered workers with status and metrics."""
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
    async def get_worker(agent_id: str, commander=Depends(get_commander)):
        """Get detailed worker info including env scan and task history."""
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
    async def send_worker_command(agent_id: str, command: str = "restart", commander=Depends(get_commander)):
        """Send a command to a worker (restart, decommission)."""
        if not commander:
            return JSONResponse(status_code=503, content={"error": "Commander not available"})

        try:
            await commander.send_command(agent_id, command)
            return {"status": "sent", "agent_id": agent_id, "command": command}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @r.delete("/api/workers/{agent_id}")
    async def remove_worker(agent_id: str, commander=Depends(get_commander)):
        """Decommission and remove a worker."""
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
