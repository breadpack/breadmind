# src/breadmind/web/routes/infrastructure.py
"""Infrastructure Hub — discover and manage local infrastructure services."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/infra", tags=["infrastructure"])

# Store discovered services and connections
_discovered: list[dict] = []
_connections: dict[str, dict] = {}  # host:port -> connection config


class ScanRequest(BaseModel):
    network: str | None = None
    scan_range: int = 20


class ConnectRequest(BaseModel):
    host: str
    port: int
    service_type: str
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    ssh_key_path: str | None = None


@router.post("/scan")
async def scan_network(body: ScanRequest) -> dict:
    """Scan local network for infrastructure services."""
    from breadmind.core.infra_discovery import discover_network

    result = await discover_network(network=body.network, scan_range=body.scan_range)

    global _discovered
    _discovered = []
    for svc in result.services_found:
        entry = {
            "host": svc.host,
            "port": svc.port,
            "service_type": svc.service_type,
            "service_name": svc.service_name,
            "response_time_ms": round(svc.response_time_ms, 1),
            "extra_info": svc.extra_info,
            "connected": f"{svc.host}:{svc.port}" in _connections,
        }
        _discovered.append(entry)

    return {
        "hosts_scanned": result.hosts_scanned,
        "services_found": len(_discovered),
        "scan_time_seconds": round(result.scan_time_seconds, 1),
        "network": result.network,
        "services": _discovered,
    }


@router.get("/services")
async def list_services() -> list[dict]:
    """List previously discovered services."""
    return _discovered


@router.post("/connect")
async def connect_service(body: ConnectRequest) -> dict:
    """Connect to a discovered service."""
    key = f"{body.host}:{body.port}"

    config: dict[str, Any] = {
        "host": body.host,
        "port": body.port,
        "service_type": body.service_type,
    }

    if body.service_type == "proxmox":
        # Set up Proxmox API connection
        config["url"] = f"https://{body.host}:{body.port}"
        config["username"] = body.username or "root@pam"
        config["password"] = body.password
        # Could also configure MCP Proxmox server here

    elif body.service_type == "kubernetes":
        config["api_server"] = f"https://{body.host}:{body.port}"
        # K8s typically uses kubeconfig

    elif body.service_type == "synology":
        config["url"] = f"https://{body.host}:{body.port}" if body.port == 5001 else f"http://{body.host}:{body.port}"
        config["username"] = body.username
        config["password"] = body.password

    elif body.service_type == "openwrt":
        config["url"] = f"http://{body.host}"
        config["username"] = body.username or "root"
        config["password"] = body.password

    elif body.service_type == "ssh":
        config["username"] = body.username or "root"
        config["ssh_key_path"] = body.ssh_key_path

        # Add to SSH allowed hosts
        from breadmind.tools.builtin import ToolSecurityConfig
        current = ToolSecurityConfig.get_config()
        allowed = current.get("allowed_ssh_hosts", [])
        if body.host not in allowed:
            allowed.append(body.host)
            ToolSecurityConfig.configure(allowed_ssh_hosts=allowed)

    _connections[key] = config

    # Persist to DB
    db = getattr(getattr(body, '_request', None), 'app', None)
    # Simple persistence via _connections dict for now

    return {"connected": True, "key": key, "service_type": body.service_type}


@router.delete("/disconnect/{host}/{port}")
async def disconnect_service(host: str, port: int) -> dict:
    key = f"{host}:{port}"
    _connections.pop(key, None)
    return {"disconnected": True, "key": key}


@router.get("/connections")
async def list_connections() -> dict:
    """List all active infrastructure connections."""
    return {
        "connections": [
            {"key": k, **{kk: vv for kk, vv in v.items() if kk != "password"}}
            for k, v in _connections.items()
        ],
        "total": len(_connections),
    }


@router.get("/summary")
async def infra_summary() -> dict:
    """Quick summary of infrastructure status."""
    by_type: dict[str, int] = {}
    for svc in _discovered:
        t = svc["service_type"]
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "discovered": len(_discovered),
        "connected": len(_connections),
        "by_type": by_type,
    }
