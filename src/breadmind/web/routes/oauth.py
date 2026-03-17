"""OAuth authentication routes for external service integrations."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


@router.get("/start/{provider}")
async def oauth_start(
    request: Request,
    provider: str,
    scopes: str = Query(default="calendar", description="Comma-separated scope names"),
) -> dict:
    """Start OAuth flow -- returns authorization URL."""
    oauth_manager = _get_oauth_manager(request)
    config = getattr(request.app.state, "config", None)

    if provider == "google":
        from breadmind.personal.oauth import GOOGLE_SCOPES
        scope_list = []
        for s in scopes.split(","):
            s = s.strip()
            if s in GOOGLE_SCOPES:
                scope_list.extend(GOOGLE_SCOPES[s])
            else:
                scope_list.append(s)

        client_id = _get_client_id(config, "google")
        redirect_uri = str(request.url_for("oauth_callback", provider="google"))

        auth_url = oauth_manager.get_auth_url(
            provider="google",
            scopes=scope_list,
            redirect_uri=redirect_uri,
            client_id=client_id,
            state=scopes,
        )
        return {"auth_url": auth_url, "provider": provider}

    elif provider == "microsoft":
        from breadmind.personal.oauth import MICROSOFT_SCOPES
        scope_list = []
        for s in scopes.split(","):
            s = s.strip()
            if s in MICROSOFT_SCOPES:
                scope_list.extend(MICROSOFT_SCOPES[s])
            else:
                scope_list.append(s)

        client_id = _get_client_id(config, "microsoft")
        redirect_uri = str(request.url_for("oauth_callback", provider="microsoft"))

        auth_url = oauth_manager.get_auth_url(
            provider="microsoft",
            scopes=scope_list,
            redirect_uri=redirect_uri,
            client_id=client_id,
            state=scopes,
        )
        return {"auth_url": auth_url, "provider": provider}

    raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")


@router.get("/callback/{provider}", name="oauth_callback")
async def oauth_callback(
    request: Request,
    provider: str,
    code: str = Query(...),
    state: str = Query(default=""),
) -> HTMLResponse:
    """Handle OAuth callback -- exchange code for tokens."""
    oauth_manager = _get_oauth_manager(request)
    config = getattr(request.app.state, "config", None)

    client_id = _get_client_id(config, provider)
    client_secret = _get_client_secret(config, provider)
    redirect_uri = str(request.url_for("oauth_callback", provider=provider))

    try:
        creds = await oauth_manager.exchange_code(
            provider=provider,
            code=code,
            redirect_uri=redirect_uri,
            client_id=client_id,
            client_secret=client_secret,
        )
        return HTMLResponse(
            content=f"""<html><body>
            <h2>\u2705 {provider} \uc778\uc99d \uc131\uacf5!</h2>
            <p>Scopes: {', '.join(creds.scopes)}</p>
            <p>\uc774 \ucc3d\uc740 \uc790\ub3d9\uc73c\ub85c \ub2eb\ud799\ub2c8\ub2e4...</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{type: 'oauth_complete', provider: '{provider}', success: true}}, '*');
                }}
                setTimeout(() => window.close(), 2000);
            </script>
            </body></html>"""
        )
    except Exception as e:
        logger.exception("OAuth callback failed for %s", provider)
        return HTMLResponse(
            content=f"""<html><body>
            <h2>\u274c \uc778\uc99d \uc2e4\ud328</h2>
            <p>{e}</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{type: 'oauth_complete', provider: '{provider}', success: false}}, '*');
                }}
            </script>
            </body></html>""",
            status_code=400,
        )


@router.get("/status/{provider}")
async def oauth_status(request: Request, provider: str) -> dict:
    """Check OAuth authentication status for a provider."""
    oauth_manager = _get_oauth_manager(request)
    creds = await oauth_manager.get_credentials(provider)
    if creds:
        return {
            "authenticated": True,
            "provider": provider,
            "scopes": creds.scopes,
            "expired": creds.is_expired,
        }
    return {"authenticated": False, "provider": provider}


@router.delete("/revoke/{provider}")
async def oauth_revoke(request: Request, provider: str) -> dict:
    """Revoke OAuth credentials for a provider."""
    oauth_manager = _get_oauth_manager(request)
    await oauth_manager.revoke(provider)
    return {"revoked": True, "provider": provider}


def _get_oauth_manager(request: Request) -> Any:
    manager = getattr(request.app.state, "oauth_manager", None)
    if not manager:
        raise HTTPException(status_code=503, detail="OAuth manager not available")
    return manager


def _get_client_id(config: Any, provider: str) -> str:
    if not config:
        raise HTTPException(status_code=500, detail="Config not available")
    if provider == "google":
        return getattr(config, "google_client_id", "") or ""
    elif provider == "microsoft":
        return getattr(config, "microsoft_client_id", "") or ""
    return ""


def _get_client_secret(config: Any, provider: str) -> str:
    if not config:
        raise HTTPException(status_code=500, detail="Config not available")
    if provider == "google":
        return getattr(config, "google_client_secret", "") or ""
    elif provider == "microsoft":
        return getattr(config, "microsoft_client_secret", "") or ""
    return ""
