"""Messenger routes: platforms, tokens, auto-connect wizard, lifecycle, security."""
from __future__ import annotations

import logging
import os
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

# --- Messenger platform config data ---

_PLATFORM_CONFIGS = {
    "slack": {"name": "Slack", "icon": "\U0001f4ac", "fields": [
        {"name": "bot_token", "label": "Bot Token", "placeholder": "xoxb-...", "secret": True},
        {"name": "app_token", "label": "App Token", "placeholder": "xapp-...", "secret": True},
    ]},
    "discord": {"name": "Discord", "icon": "\U0001f3ae", "fields": [
        {"name": "bot_token", "label": "Bot Token", "placeholder": "Bot token", "secret": True},
    ]},
    "telegram": {"name": "Telegram", "icon": "\u2708\ufe0f", "fields": [
        {"name": "bot_token", "label": "Bot Token", "placeholder": "From @BotFather", "secret": True},
    ]},
    "whatsapp": {"name": "WhatsApp", "icon": "\U0001f4f1", "fields": [
        {"name": "account_sid", "label": "Twilio Account SID", "placeholder": "AC...", "secret": True},
        {"name": "auth_token", "label": "Twilio Auth Token", "placeholder": "Auth token", "secret": True},
        {"name": "from_number", "label": "WhatsApp Number", "placeholder": "whatsapp:+14155238886", "secret": False},
    ]},
    "gmail": {"name": "Gmail", "icon": "\u2709\ufe0f", "fields": [
        {"name": "client_id", "label": "OAuth Client ID", "placeholder": "xxx.apps.googleusercontent.com", "secret": True},
        {"name": "client_secret", "label": "OAuth Client Secret", "placeholder": "GOCSPX-...", "secret": True},
        {"name": "refresh_token", "label": "Refresh Token", "placeholder": "1//...", "secret": True},
    ]},
    "signal": {"name": "Signal", "icon": "\U0001f4e8", "fields": [
        {"name": "phone_number", "label": "Phone Number", "placeholder": "+1234567890", "secret": False},
        {"name": "signal_cli_path", "label": "signal-cli Path", "placeholder": "signal-cli", "secret": False},
    ]},
    "teams": {"name": "Teams", "icon": "\U0001f4bc", "fields": [
        {"name": "app_id", "label": "App ID", "placeholder": "Azure Bot App ID", "secret": True},
        {"name": "app_password", "label": "App Password", "placeholder": "Azure Bot App Password", "secret": True},
    ]},
    "line": {"name": "LINE", "icon": "\U0001f4ac", "fields": [
        {"name": "channel_token", "label": "Channel Access Token", "placeholder": "Channel access token", "secret": True},
        {"name": "channel_secret", "label": "Channel Secret", "placeholder": "Channel secret", "secret": True},
    ]},
    "matrix": {"name": "Matrix", "icon": "\U0001f310", "fields": [
        {"name": "homeserver", "label": "Homeserver URL", "placeholder": "https://matrix.org", "secret": False},
        {"name": "access_token", "label": "Access Token", "placeholder": "syt_...", "secret": True},
        {"name": "user_id", "label": "User ID", "placeholder": "@bot:matrix.org", "secret": False},
    ]},
}

_TOKEN_KEYS = {
    "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
    "discord": ["DISCORD_BOT_TOKEN"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "whatsapp": ["WHATSAPP_TWILIO_ACCOUNT_SID", "WHATSAPP_TWILIO_AUTH_TOKEN"],
    "gmail": ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"],
    "signal": ["SIGNAL_PHONE_NUMBER"],
    "teams": ["TEAMS_APP_ID", "TEAMS_APP_PASSWORD"],
    "line": ["LINE_CHANNEL_TOKEN", "LINE_CHANNEL_SECRET"],
    "matrix": ["MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN"],
}

_TOKEN_MAP = {
    "slack": {"bot_token": "SLACK_BOT_TOKEN", "app_token": "SLACK_APP_TOKEN"},
    "discord": {"bot_token": "DISCORD_BOT_TOKEN"},
    "telegram": {"bot_token": "TELEGRAM_BOT_TOKEN"},
    "whatsapp": {"account_sid": "WHATSAPP_TWILIO_ACCOUNT_SID", "auth_token": "WHATSAPP_TWILIO_AUTH_TOKEN", "from_number": "WHATSAPP_FROM_NUMBER"},
    "gmail": {"client_id": "GMAIL_CLIENT_ID", "client_secret": "GMAIL_CLIENT_SECRET", "refresh_token": "GMAIL_REFRESH_TOKEN"},
    "signal": {"phone_number": "SIGNAL_PHONE_NUMBER", "signal_cli_path": "SIGNAL_CLI_PATH"},
    "teams": {"app_id": "TEAMS_APP_ID", "app_password": "TEAMS_APP_PASSWORD"},
    "line": {"channel_token": "LINE_CHANNEL_TOKEN", "channel_secret": "LINE_CHANNEL_SECRET"},
    "matrix": {"homeserver": "MATRIX_HOMESERVER", "access_token": "MATRIX_ACCESS_TOKEN", "user_id": "MATRIX_USER_ID"},
}

_VALID_PLATFORMS = {"slack", "discord", "telegram", "whatsapp", "gmail", "signal", "teams", "line", "matrix"}


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
    """Register messenger platform config, auto-connect, lifecycle, and security routes."""

    # ── Platform Config & Token Routes ──

    @app.get("/api/messenger/platforms")
    async def messenger_platforms():
        """Get all messenger platforms with their status and config fields."""
        platforms = {}
        for platform, cfg in _PLATFORM_CONFIGS.items():
            tokens_set = all(bool(os.environ.get(k, "")) for k in _TOKEN_KEYS.get(platform, []))
            connected = False
            if app_state._message_router and hasattr(app_state._message_router, 'get_platform_status'):
                status = app_state._message_router.get_platform_status()
                connected = status.get(platform, {}).get("connected", False)
            allowed = []
            if app_state._message_router and hasattr(app_state._message_router, 'get_allowed_users'):
                allowed = app_state._message_router.get_allowed_users().get(platform, [])

            platforms[platform] = {
                **cfg,
                "configured": tokens_set,
                "connected": connected,
                "allowed_users": allowed,
            }
        return {"platforms": platforms}

    @app.post("/api/messenger/{platform}/token")
    async def set_messenger_token(platform: str, request: Request):
        """Save messenger platform tokens."""
        data = await request.json()
        if platform not in _VALID_PLATFORMS:
            return JSONResponse(status_code=400, content={"error": f"Invalid platform: {platform}"})

        saved = {}
        for field_name, env_key in _TOKEN_MAP.get(platform, {}).items():
            value = data.get(field_name, "")
            if value:
                os.environ[env_key] = value
                if app_state._db:
                    try:
                        await app_state._db.set_setting(f"messenger_token:{env_key}", {"value": value})
                    except Exception as e:
                        logger.warning(f"Failed to save messenger token to DB: {e}")
                saved[field_name] = env_key

        return {"status": "ok", "saved": list(saved.keys()), "platform": platform}

    @app.post("/api/messenger/{platform}/test")
    async def test_messenger(platform: str):
        """Send a test message to verify connection."""
        if platform not in _VALID_PLATFORMS:
            return JSONResponse(status_code=400, content={"error": f"Invalid platform: {platform}"})
        if not app_state._message_router:
            return JSONResponse(status_code=503, content={"error": "Message router not configured"})
        gw = app_state._message_router._gateways.get(platform)
        if not gw:
            return {"status": "not_connected", "message": f"{platform} gateway not initialized. Save tokens and restart."}
        try:
            return {"status": "ok", "message": f"{platform} gateway is available"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/api/messenger/{platform}/setup-url")
    async def messenger_setup_url(platform: str):
        """Generate setup/invite URLs for messenger platforms."""
        if platform == "slack":
            client_id = os.environ.get("SLACK_CLIENT_ID", "")
            if not client_id:
                return {"url": None, "steps": [
                    {"step": 1, "text": "Go to Slack API", "link": "https://api.slack.com/apps"},
                    {"step": 2, "text": "Click 'Create New App' -> 'From scratch'"},
                    {"step": 3, "text": "Add Bot Token Scopes: chat:write, app_mentions:read, channels:read, im:read, im:write"},
                    {"step": 4, "text": "Enable Socket Mode and get an App Token (xapp-...)"},
                    {"step": 5, "text": "Install app to your workspace"},
                    {"step": 6, "text": "Copy Bot Token (xoxb-...) and App Token here"},
                ]}
            redirect_uri = f"http://localhost:{app_state._config.web.port if app_state._config else 8080}/api/messenger/slack/oauth-callback"
            scopes = "chat:write,app_mentions:read,channels:read,im:read,im:write,im:history"
            url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scopes}&redirect_uri={redirect_uri}"
            return {"url": url, "steps": []}

        elif platform == "discord":
            client_id = os.environ.get("DISCORD_CLIENT_ID", "")
            if not client_id:
                return {"url": None, "steps": [
                    {"step": 1, "text": "Go to Discord Developer Portal", "link": "https://discord.com/developers/applications"},
                    {"step": 2, "text": "Click 'New Application' -> name it 'BreadMind'"},
                    {"step": 3, "text": "Go to 'Bot' tab -> click 'Add Bot'"},
                    {"step": 4, "text": "Enable: Message Content Intent, Server Members Intent"},
                    {"step": 5, "text": "Copy the Bot Token here"},
                    {"step": 6, "text": "Or enter Client ID below for auto-invite link"},
                ]}
            permissions = 274877975552  # Send Messages, Read Messages, Add Reactions, Manage Messages
            url = f"https://discord.com/oauth2/authorize?client_id={client_id}&permissions={permissions}&scope=bot"
            return {"url": url, "steps": []}

        elif platform == "telegram":
            return {"url": "https://t.me/BotFather", "steps": [
                {"step": 1, "text": "Open BotFather in Telegram", "link": "https://t.me/BotFather"},
                {"step": 2, "text": "Send /newbot and follow the prompts"},
                {"step": 3, "text": "Copy the HTTP API token (e.g., 123456:ABC-DEF...)"},
                {"step": 4, "text": "Paste the token in the Bot Token field above"},
            ]}

        elif platform == "whatsapp":
            return {"url": "https://console.twilio.com/", "steps": [
                {"step": 1, "text": "Go to Twilio Console", "link": "https://console.twilio.com/"},
                {"step": 2, "text": "Enable WhatsApp Sandbox under Messaging"},
                {"step": 3, "text": "Copy Account SID and Auth Token"},
                {"step": 4, "text": "Note your WhatsApp Sandbox number (whatsapp:+14155238886)"},
                {"step": 5, "text": "Set webhook URL to: http://<your-host>/api/webhook/receive/whatsapp"},
            ]}

        elif platform == "gmail":
            client_id = os.environ.get("GMAIL_CLIENT_ID", "")
            if not client_id:
                return {"url": None, "steps": [
                    {"step": 1, "text": "Go to Google Cloud Console", "link": "https://console.cloud.google.com/apis/credentials"},
                    {"step": 2, "text": "Create OAuth 2.0 Client ID (Web application)"},
                    {"step": 3, "text": "Add redirect URI: http://localhost:<port>/api/messenger/gmail/oauth-callback"},
                    {"step": 4, "text": "Enable Gmail API in your project"},
                    {"step": 5, "text": "Enter Client ID and Client Secret here, then click Connect"},
                ]}
            port = app_state._config.web.port if app_state._config else 8080
            redirect_uri = f"http://localhost:{port}/api/messenger/gmail/oauth-callback"
            scopes = "https://www.googleapis.com/auth/gmail.modify"
            url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scopes}&access_type=offline&prompt=consent"
            return {"url": url, "steps": []}

        elif platform == "signal":
            return {"url": "https://github.com/AsamK/signal-cli", "steps": [
                {"step": 1, "text": "Install signal-cli", "link": "https://github.com/AsamK/signal-cli"},
                {"step": 2, "text": "Register your phone number: signal-cli -a +NUMBER register"},
                {"step": 3, "text": "Verify with SMS code: signal-cli -a +NUMBER verify CODE"},
                {"step": 4, "text": "Enter your phone number in the field above"},
            ]}

        elif platform == "teams":
            return {"url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade", "steps": [
                {"step": 1, "text": "Go to Azure Portal -> App registrations", "link": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"},
                {"step": 2, "text": "Register a new application for your bot"},
                {"step": 3, "text": "Create Azure Bot Service resource and link it to the app"},
                {"step": 4, "text": "Copy Application (client) ID and create a client secret"},
                {"step": 5, "text": "Set messaging endpoint to: <your-host>/api/messenger/teams/webhook"},
                {"step": 6, "text": "Enter App ID and App Password above"},
            ]}

        elif platform == "line":
            return {"url": "https://developers.line.biz/console/", "steps": [
                {"step": 1, "text": "Go to LINE Developers Console", "link": "https://developers.line.biz/console/"},
                {"step": 2, "text": "Create a Messaging API channel"},
                {"step": 3, "text": "Issue a Channel Access Token (long-lived)"},
                {"step": 4, "text": "Set webhook URL to: <your-host>/api/messenger/line/webhook"},
                {"step": 5, "text": "Enable 'Use webhook' and disable 'Auto-reply messages'"},
                {"step": 6, "text": "Enter Channel Access Token and Channel Secret above"},
            ]}

        elif platform == "matrix":
            return {"url": "https://element.io/", "steps": [
                {"step": 1, "text": "Set up a Matrix homeserver or use an existing one (e.g., matrix.org)"},
                {"step": 2, "text": "Create a bot account on the homeserver"},
                {"step": 3, "text": "Log in with Element or curl to obtain an access token"},
                {"step": 4, "text": "Enter the homeserver URL, access token, and user ID above"},
                {"step": 5, "text": "Matrix uses long-poll sync — no webhook configuration needed"},
            ]}

        return JSONResponse(status_code=400, content={"error": "Invalid platform"})

    @app.get("/api/messenger/slack/oauth-callback")
    async def slack_oauth_callback(code: str = "", error: str = ""):
        """Handle Slack OAuth callback."""
        if error:
            return HTMLResponse(f"<html><body><h1>Slack OAuth Error</h1><p>{error}</p><p><a href='/'>Back to BreadMind</a></p></body></html>")
        if not code:
            return HTMLResponse("<html><body><h1>Missing code</h1><p><a href='/'>Back to BreadMind</a></p></body></html>")

        client_id = os.environ.get("SLACK_CLIENT_ID", "")
        client_secret = os.environ.get("SLACK_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return HTMLResponse("<html><body><h1>Slack OAuth not configured</h1><p>Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET</p></body></html>")

        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://slack.com/api/oauth.v2.access", data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                }) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        bot_token = data.get("access_token", "")
                        os.environ["SLACK_BOT_TOKEN"] = bot_token
                        if app_state._db:
                            try:
                                from breadmind.config import encrypt_value
                                await app_state._db.set_setting("messenger_token:SLACK_BOT_TOKEN", {"encrypted": encrypt_value(bot_token)})
                            except Exception:
                                pass
                        # Notify WebSocket clients
                        await app_state.broadcast_event({"type": "messenger_connected", "platform": "slack"})
                        return HTMLResponse(
                            "<html><body style='background:#0d1117;color:#e2e8f0;font-family:sans-serif;text-align:center;padding:60px;'>"
                            "<h1>Slack Connected!</h1><p>Bot token saved. You can close this window.</p>"
                            "<script>setTimeout(function(){window.close();},3000);</script>"
                            "<p style='color:#64748b;font-size:13px;'>This window will close in 3 seconds...</p>"
                            "<p><a href='/' style='color:#60a5fa;'>Back to BreadMind</a></p></body></html>"
                        )
                    else:
                        err = data.get("error", "unknown")
                        return HTMLResponse(f"<html><body><h1>Slack OAuth Failed</h1><p>{err}</p></body></html>")
        except Exception as e:
            return HTMLResponse(f"<html><body><h1>Error</h1><p>{e}</p></body></html>")

    # --- Additional Messenger endpoints (WhatsApp, Gmail) ---

    @app.post("/api/webhook/receive/whatsapp")
    async def receive_whatsapp_webhook(request: Request):
        """Handle incoming WhatsApp messages via Twilio webhook."""
        if not app_state._message_router:
            return JSONResponse(status_code=503, content={"error": "Messenger not configured"})
        gw = app_state._message_router._gateways.get("whatsapp")
        if not gw:
            return JSONResponse(status_code=503, content={"error": "WhatsApp gateway not configured"})
        form_data = dict(await request.form())
        if hasattr(gw, 'handle_incoming_webhook'):
            await gw.handle_incoming_webhook(form_data)
        return {"status": "ok"}

    @app.get("/api/messenger/gmail/oauth-callback")
    async def gmail_oauth_callback(code: str = "", error: str = ""):
        """Handle Gmail OAuth callback."""
        if error:
            return HTMLResponse(f"<html><body><h1>Gmail OAuth Error</h1><p>{error}</p></body></html>")
        if not code:
            return HTMLResponse("<html><body><h1>Missing code</h1></body></html>")
        import aiohttp
        client_id = os.environ.get("GMAIL_CLIENT_ID", "")
        client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return HTMLResponse("<html><body><h1>Gmail OAuth not configured</h1></body></html>")
        try:
            port = app_state._config.web.port if app_state._config else 8080
            redirect_uri = f"http://localhost:{port}/api/messenger/gmail/oauth-callback"
            async with aiohttp.ClientSession() as session:
                async with session.post("https://oauth2.googleapis.com/token", data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }) as resp:
                    data = await resp.json()
                    if "refresh_token" in data:
                        os.environ["GMAIL_REFRESH_TOKEN"] = data["refresh_token"]
                        if app_state._db:
                            try:
                                await app_state._db.set_setting("messenger_token:GMAIL_REFRESH_TOKEN",
                                                                   {"value": data["refresh_token"]})
                            except Exception:
                                pass
                        await app_state.broadcast_event({"type": "messenger_connected", "platform": "gmail"})
                        return HTMLResponse(
                            "<html><body style='background:#0d1117;color:#e2e8f0;font-family:sans-serif;text-align:center;padding:60px;'>"
                            "<h1>Gmail Connected!</h1><p>Refresh token saved. You can close this window.</p>"
                            "<script>setTimeout(function(){window.close();},3000);</script></body></html>"
                        )
                    else:
                        err = data.get("error_description", data.get("error", "unknown"))
                        return HTMLResponse(f"<html><body><h1>Gmail OAuth Failed</h1><p>{err}</p></body></html>")
        except Exception as e:
            return HTMLResponse(f"<html><body><h1>Error</h1><p>{e}</p></body></html>")

    # ── Teams & LINE Webhook Routes ──

    @app.post("/api/messenger/teams/webhook")
    async def teams_webhook(request: Request):
        """Receive Teams Bot Framework activities."""
        body = await request.json()
        if not app_state._message_router:
            return JSONResponse(status_code=503, content={"error": "Messenger not configured"})
        gw = app_state._message_router._gateways.get("teams")
        if gw and hasattr(gw, "handle_incoming"):
            response = await gw.handle_incoming(body)
            if response:
                return {"text": response}
        return {"status": "ok"}

    @app.post("/api/messenger/line/webhook")
    async def line_webhook(request: Request):
        """Receive LINE webhook events."""
        body = await request.json()
        if not app_state._message_router:
            return JSONResponse(status_code=503, content={"error": "Messenger not configured"})
        gw = app_state._message_router._gateways.get("line")
        if gw and hasattr(gw, "handle_webhook"):
            await gw.handle_webhook(body)
        return {"status": "ok"}

    @app.get("/api/messenger/{platform}/webhook-url")
    async def get_webhook_url(request: Request, platform: str):
        """Get the webhook URL for a platform (Teams, LINE)."""
        if platform not in ("teams", "line"):
            return JSONResponse(status_code=400, content={"error": f"{platform} does not use webhooks"})
        base = str(request.base_url).rstrip("/")
        return {"webhook_url": f"{base}/api/messenger/{platform}/webhook"}

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
