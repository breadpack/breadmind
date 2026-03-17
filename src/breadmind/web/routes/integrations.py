"""Integration Hub — unified external service management."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class ServiceCredentials(BaseModel):
    """Generic credentials payload for service authentication."""
    api_key: str | None = None
    api_token: str | None = None
    email: str | None = None
    base_url: str | None = None
    project_key: str | None = None
    owner: str | None = None
    repo: str | None = None
    database_id: str | None = None
    token: str | None = None


# Service definitions
SERVICES = {
    "google_calendar": {"name": "Google Calendar", "category": "productivity", "auth": "oauth", "provider": "google", "scopes": "calendar"},
    "google_drive": {"name": "Google Drive", "category": "files", "auth": "oauth", "provider": "google", "scopes": "drive"},
    "google_contacts": {"name": "Google Contacts", "category": "contacts", "auth": "oauth", "provider": "google", "scopes": "contacts"},
    "outlook_calendar": {"name": "Outlook Calendar", "category": "productivity", "auth": "oauth", "provider": "microsoft", "scopes": "calendar"},
    "onedrive": {"name": "OneDrive", "category": "files", "auth": "oauth", "provider": "microsoft", "scopes": "files"},
    "notion": {"name": "Notion", "category": "productivity", "auth": "api_key", "adapter_source": "notion"},
    "jira": {"name": "Jira", "category": "productivity", "auth": "api_token", "adapter_source": "jira"},
    "github": {"name": "GitHub Issues", "category": "productivity", "auth": "token", "adapter_source": "github"},
    "slack": {"name": "Slack", "category": "messenger", "auth": "token"},
    "discord": {"name": "Discord", "category": "messenger", "auth": "token"},
    "telegram": {"name": "Telegram", "category": "messenger", "auth": "token"},
    "teams": {"name": "Microsoft Teams", "category": "messenger", "auth": "app_credentials"},
    "line": {"name": "LINE", "category": "messenger", "auth": "token"},
    "matrix": {"name": "Matrix", "category": "messenger", "auth": "token"},
}


@router.get("/services")
async def list_services(request: Request, category: str | None = None) -> list[dict]:
    """List all available services with their connection status."""
    services = []
    for service_id, info in SERVICES.items():
        if category and info["category"] != category:
            continue
        connected = await _check_connection(request, service_id, info)
        services.append({
            "id": service_id,
            "name": info["name"],
            "category": info["category"],
            "auth_type": info["auth"],
            "connected": connected,
        })
    return services


@router.get("/services/{service_id}")
async def get_service_status(request: Request, service_id: str) -> dict:
    """Get detailed status for a specific service."""
    if service_id not in SERVICES:
        raise HTTPException(404, f"Unknown service: {service_id}")

    info = SERVICES[service_id]
    connected = await _check_connection(request, service_id, info)

    result = {
        "id": service_id,
        "name": info["name"],
        "category": info["category"],
        "auth_type": info["auth"],
        "connected": connected,
    }

    # Add OAuth URL for OAuth services
    if info["auth"] == "oauth" and not connected:
        oauth_mgr = getattr(request.app.state, "oauth_manager", None)
        if oauth_mgr:
            result["connect_url"] = f"/api/oauth/start/{info['provider']}?scopes={info.get('scopes', '')}"

    return result


@router.post("/services/{service_id}/connect")
async def connect_service(request: Request, service_id: str, body: ServiceCredentials) -> dict:
    """Connect a service with provided credentials."""
    if service_id not in SERVICES:
        raise HTTPException(404, f"Unknown service: {service_id}")

    info = SERVICES[service_id]

    if info["auth"] == "oauth":
        # OAuth services redirect to OAuth flow
        return {"redirect": f"/api/oauth/start/{info['provider']}?scopes={info.get('scopes', '')}"}

    # API key/token services — authenticate the adapter directly
    registry = getattr(request.app.state, "adapter_registry", None)
    if not registry:
        raise HTTPException(503, "Adapter registry not available")

    adapter_source = info.get("adapter_source", service_id)

    # Find adapter and authenticate
    try:
        adapters = registry.list_adapters()
        adapter = None
        for a in adapters:
            if a.source == adapter_source:
                adapter = a
                break

        if not adapter:
            raise HTTPException(404, f"Adapter for {service_id} not registered")

        creds = body.model_dump(exclude_none=True)
        try:
            success = await adapter.authenticate(creds)
        except ValueError as e:
            raise HTTPException(422, str(e))

        if success:
            # Save credentials to DB
            db = getattr(request.app.state, "db", None)
            if db:
                import json
                await db.set_setting(f"integration:{service_id}", json.dumps(creds))

            return {"connected": True, "service": service_id}
        else:
            raise HTTPException(401, "Authentication failed")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Connection failed: {e}")


@router.delete("/services/{service_id}/disconnect")
async def disconnect_service(request: Request, service_id: str) -> dict:
    """Disconnect a service."""
    if service_id not in SERVICES:
        raise HTTPException(404, f"Unknown service: {service_id}")

    info = SERVICES[service_id]

    if info["auth"] == "oauth":
        oauth_mgr = getattr(request.app.state, "oauth_manager", None)
        if oauth_mgr:
            await oauth_mgr.revoke(info["provider"])

    # Remove stored credentials
    db = getattr(request.app.state, "db", None)
    if db:
        await db.set_setting(f"integration:{service_id}", None)

    return {"disconnected": True, "service": service_id}


@router.get("/health")
async def integration_health(request: Request) -> list[dict]:
    """Check health of all integration tokens."""
    monitor = getattr(request.app.state, "token_monitor", None)
    if not monitor:
        # Fallback: check OAuth only
        oauth_mgr = getattr(request.app.state, "oauth_manager", None)
        if not oauth_mgr:
            return []

        import time

        statuses = []
        for provider in ["google", "microsoft"]:
            creds = await oauth_mgr.get_credentials(provider)
            if creds:
                expires_in = (creds.expires_at - time.time()) / 3600
                statuses.append({
                    "service": provider,
                    "healthy": not creds.is_expired,
                    "message": "정상" if not creds.is_expired else "토큰 만료",
                    "expires_in_hours": round(expires_in, 1),
                })
        return statuses

    await monitor.check_all()
    alerts = await monitor.get_alerts()
    return [
        {
            "service": s.service_id,
            "name": s.service_name,
            "healthy": s.healthy,
            "message": s.message,
            "expires_in_hours": s.expires_in_hours,
        }
        for s in alerts
    ]


@router.get("/summary")
async def integration_summary(request: Request) -> dict:
    """Quick summary of all integration statuses."""
    services = await list_services(request)
    total = len(services)
    connected = sum(1 for s in services if s["connected"])

    by_category: dict[str, dict] = {}
    for s in services:
        cat = s["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0, "connected": 0}
        by_category[cat]["total"] += 1
        if s["connected"]:
            by_category[cat]["connected"] += 1

    return {
        "total": total,
        "connected": connected,
        "categories": by_category,
    }


async def _check_connection(request: Request, service_id: str, info: dict) -> bool:
    """Check if a service is currently connected."""
    if info["auth"] == "oauth":
        oauth_mgr = getattr(request.app.state, "oauth_manager", None)
        if oauth_mgr:
            creds = await oauth_mgr.get_credentials(info["provider"])
            return creds is not None and not creds.is_expired
        return False

    if info["category"] == "messenger":
        # Check messenger gateway status
        lifecycle = getattr(request.app.state, "lifecycle_manager", None)
        if lifecycle:
            return lifecycle.is_running(service_id)
        return False

    # Check if we have stored credentials
    db = getattr(request.app.state, "db", None)
    if db:
        stored = await db.get_setting(f"integration:{service_id}")
        return stored is not None


    return False
