"""System routes: setup, auth, update, scheduler, subagent, webhook, container, messenger, health."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


def setup_system_routes(r: APIRouter, app_state):
    """Register system-level routes."""

    # --- Setup wizard endpoints ---

    @r.get("/api/setup/status")
    async def setup_status():
        """Check if first-run setup is needed."""
        from breadmind.core.setup_wizard import is_first_run_async
        first_run = await is_first_run_async(app_state._db)
        return {"first_run": first_run}

    @r.get("/api/setup/providers")
    async def setup_providers():
        """List available LLM providers for setup."""
        from breadmind.llm.factory import get_provider_options
        return {"providers": get_provider_options()}

    @r.post("/api/setup/validate")
    async def setup_validate(request: Request):
        """Validate an API key for a provider."""
        data = await request.json()
        provider_id = data.get("provider", "")
        api_key = data.get("api_key", "")
        from breadmind.core.setup_wizard import validate_api_key
        result = await validate_api_key(provider_id, api_key)
        return result

    @r.post("/api/setup/complete")
    async def setup_complete(request: Request):
        """Save provider config and mark setup as done."""
        data = await request.json()
        provider_id = data.get("provider", "")
        api_key = data.get("api_key", "")
        model = data.get("model", "")

        from breadmind.llm.factory import get_provider_options
        from breadmind.core.setup_wizard import mark_setup_complete

        # Find provider info
        options = get_provider_options()
        provider_info = next((p for p in options if p["id"] == provider_id), None)
        if not provider_info:
            return JSONResponse(status_code=400, content={"error": "Invalid provider"})

        # Save API key
        env_key = provider_info.get("env_key")
        if env_key and api_key:
            os.environ[env_key] = api_key
            if app_state._db:
                try:
                    from breadmind.config import save_api_key_to_db
                    await save_api_key_to_db(app_state._db, env_key, api_key)
                except Exception:
                    from breadmind.config import save_env_var
                    save_env_var(env_key, api_key)
            else:
                from breadmind.config import save_env_var
                save_env_var(env_key, api_key)

        # Save provider config
        if not model:
            model = provider_info["models"][0]
        if app_state._config:
            app_state._config.llm.default_provider = provider_id
            app_state._config.llm.default_model = model
        if app_state._db:
            await app_state._db.set_setting("llm", {
                "default_provider": provider_id,
                "default_model": model,
                "tool_call_max_turns": app_state._config.llm.tool_call_max_turns if app_state._config else 10,
                "tool_call_timeout_seconds": app_state._config.llm.tool_call_timeout_seconds if app_state._config else 30,
            })

        # Hot-swap the agent's LLM provider so chat works immediately
        if app_state._agent and app_state._config:
            try:
                from breadmind.llm.factory import create_provider
                new_provider = create_provider(app_state._config)
                await app_state._agent.update_provider(new_provider)
            except Exception as e:
                logger.warning(f"Failed to hot-swap provider: {e}")

        await mark_setup_complete(app_state._db)
        return {"status": "ok", "provider": provider_id, "model": model}

    @r.get("/api/setup/discover")
    async def setup_discover():
        """Discover local infrastructure environment and auto-set specialties."""
        from breadmind.core.setup_wizard import discover_environment
        env = await discover_environment()
        # Auto-set specialties from discovered infra
        specialties = env.detected_specialties()
        if specialties and app_state._config:
            persona = app_state._config._persona or {}
            persona["specialties"] = specialties
            app_state._config._persona = persona
            if app_state._db:
                try:
                    await app_state._db.set_setting("persona", persona)
                except Exception:
                    pass
        return {
            "environment": env.to_dict(),
            "summary": env.summary(),
            "specialties": specialties,
        }

    @r.post("/api/setup/recommend")
    async def setup_recommend():
        """Use LLM to generate setup recommendations based on environment."""
        from breadmind.core.setup_wizard import discover_environment, generate_recommendations

        env = await discover_environment()

        # Create a fresh provider with the newly saved key
        handler = app_state._message_handler
        try:
            from breadmind.llm.factory import create_provider
            if app_state._config:
                provider = create_provider(app_state._config)
                from breadmind.llm.base import LLMMessage
                async def fresh_handler(msg, user="setup", channel="setup"):
                    resp = await provider.chat([
                        LLMMessage(role="system", content="You are BreadMind, an AI infrastructure agent."),
                        LLMMessage(role="user", content=msg),
                    ])
                    return resp.content or ""
                handler = fresh_handler
        except Exception:
            pass

        recommendations = await generate_recommendations(env, handler)
        return {"environment": env.to_dict(), "recommendations": recommendations}

    # --- Auth endpoints ---

    @r.post("/api/auth/login")
    async def login(request: Request):
        """Authenticate with password."""
        if not app_state._auth or not app_state._auth.enabled:
            return {"status": "ok", "message": "Auth disabled"}
        data = await request.json()
        password = data.get("password", "")
        if app_state._auth.verify_password(password):
            token = app_state._auth.create_session(
                ip=request.client.host if request.client else "",
                user_agent=request.headers.get("user-agent", ""),
            )
            response = JSONResponse({"status": "ok", "token": token})
            response.set_cookie(
                "breadmind_session", token,
                httponly=True, samesite="strict",
                max_age=app_state._auth._session_timeout,
            )
            return response
        return JSONResponse(status_code=401, content={"error": "Invalid password"})

    @r.post("/api/auth/logout")
    async def logout(request: Request):
        token = request.cookies.get("breadmind_session", "")
        if app_state._auth and token:
            app_state._auth.revoke_session(token)
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("breadmind_session")
        return response

    @r.get("/api/auth/status")
    async def auth_status(request: Request):
        if not app_state._auth or not app_state._auth.enabled:
            return {"auth_enabled": False, "authenticated": True}
        authenticated = app_state._auth.authenticate_request(request)
        return {
            "auth_enabled": True,
            "authenticated": authenticated,
            "sessions": app_state._auth.get_active_sessions(),
        }

    @r.post("/api/auth/setup")
    async def setup_auth(request: Request):
        """Initial password setup (only works when no password is set)."""
        if app_state._auth and app_state._auth._password_hash:
            return JSONResponse(status_code=403, content={"error": "Password already configured"})
        data = await request.json()
        password = data.get("password", "")
        if len(password) < 8:
            return JSONResponse(status_code=400, content={"error": "Password must be at least 8 characters"})
        from breadmind.web.auth import AuthManager
        pw_hash = AuthManager.hash_password(password)
        if app_state._auth:
            app_state._auth._password_hash = pw_hash
            app_state._auth._enabled = True
        # Persist to DB
        if app_state._db:
            try:
                await app_state._db.set_setting("auth", {"password_hash": pw_hash, "enabled": True})
            except Exception:
                pass
        token = app_state._auth.create_session() if app_state._auth else ""
        response = JSONResponse({"status": "ok", "message": "Password set successfully"})
        if token:
            response.set_cookie("breadmind_session", token, httponly=True, samesite="strict")
        return response

    # --- Health endpoint ---

    @r.get("/health")
    async def health():
        agent_ok = app_state._message_handler is not None
        monitoring_ok = (
            app_state._monitoring_engine is not None
            and app_state._monitoring_engine.get_status()["running"]
        ) if app_state._monitoring_engine is not None else False

        components = {
            "agent": agent_ok,
            "monitoring": monitoring_ok,
        }

        # Agent is critical - if not configured, return 503
        if not agent_ok:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "components": components},
            )

        return {"status": "ok", "components": components}

    # --- Update endpoints ---

    @r.get("/api/update/check")
    async def check_update():
        """Check for new version from PyPI or GitHub."""
        import aiohttp
        current = "0.1.0"
        latest = current
        update_available = False
        release_notes = ""

        try:
            # Try PyPI first
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://pypi.org/pypi/breadmind/json",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        latest = data.get("info", {}).get("version", current)
                        release_notes = data.get("info", {}).get("summary", "")
        except Exception:
            pass

        if latest == current:
            # Try GitHub releases
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://api.github.com/repos/breadpack/breadmind/releases/latest",
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            tag = data.get("tag_name", "").lstrip("v")
                            if tag:
                                latest = tag
                                release_notes = data.get("body", "")[:500]
            except Exception:
                pass

        # Simple version comparison
        try:
            from packaging.version import Version
            update_available = Version(latest) > Version(current)
        except Exception:
            update_available = latest != current and latest > current

        return {
            "current": current,
            "latest": latest,
            "update_available": update_available,
            "release_notes": release_notes,
        }

    @r.post("/api/update/apply")
    async def apply_update():
        """Apply update by running pip install --upgrade."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "--upgrade", "breadmind",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace")
            if proc.returncode == 0:
                return {
                    "status": "ok",
                    "message": "Update installed. Restart the service to apply.",
                    "output": output[-500:],
                    "restart_required": True,
                }
            else:
                # Try GitHub fallback
                proc2 = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "pip", "install", "--upgrade",
                    "git+https://github.com/breadpack/breadmind.git",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout2, stderr2 = await proc2.communicate()
                if proc2.returncode == 0:
                    return {
                        "status": "ok",
                        "message": "Update installed from GitHub. Restart the service to apply.",
                        "output": stdout2.decode("utf-8", errors="replace")[-500:],
                        "restart_required": True,
                    }
                return {
                    "status": "error",
                    "message": "Update failed",
                    "output": stderr.decode("utf-8", errors="replace")[-500:],
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @r.post("/api/update/restart")
    async def restart_service():
        """Restart the BreadMind service after update."""
        import platform as _platform
        try:
            if _platform.system() == "Windows":
                # Try NSSM restart
                nssm_path = os.path.join(os.environ.get("APPDATA", ""), "breadmind", "bin", "nssm.exe")
                if os.path.exists(nssm_path):
                    proc = await asyncio.create_subprocess_exec(
                        nssm_path, "restart", "BreadMind",
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()
                    return {"status": "ok", "message": "Service restarting..."}
            else:
                # Try systemctl restart
                proc = await asyncio.create_subprocess_exec(
                    "sudo", "systemctl", "restart", "breadmind",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                return {"status": "ok", "message": "Service restarting..."}

            return {"status": "manual", "message": "Please restart the service manually."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @r.post("/api/system/uninstall")
    async def uninstall_system(request: Request):
        """Complete uninstall -- stops service, removes config, DB, Docker resources."""
        data = await request.json()
        keep_db = data.get("keep_db", False)
        keep_config = data.get("keep_config", False)

        results = []
        try:
            from breadmind.uninstall import (
                stop_service, remove_service_files, remove_config,
                drop_database, remove_docker_resources,
            )
            from breadmind.config import get_default_config_dir
            config_dir = get_default_config_dir()

            remove_service_files()
            results.append("service_files: removed")

            if not keep_config:
                remove_config(config_dir)
                results.append("config: removed")

            if not keep_db:
                await drop_database(config_dir)
                results.append("database: cleaned")

            remove_docker_resources()
            results.append("docker: cleaned")

            results.append("status: ok")
        except Exception as e:
            results.append(f"error: {e}")

        return {"results": results, "message": "Uninstall complete. Stop the service manually or it will shut down."}

    # --- Scheduler endpoints ---

    @r.get("/api/scheduler/status")
    async def scheduler_status():
        if not app_state._scheduler:
            return {"status": {"running": False, "cron_jobs": 0, "heartbeats": 0, "total_runs": 0}}
        return {"status": app_state._scheduler.get_status()}

    @r.get("/api/scheduler/cron")
    async def list_cron_jobs():
        if not app_state._scheduler:
            return {"jobs": []}
        return {"jobs": app_state._scheduler.get_cron_jobs()}

    @r.post("/api/scheduler/cron")
    async def add_cron_job(request: Request):
        if not app_state._scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        data = await request.json()
        import uuid
        job_id = data.get("id", str(uuid.uuid4())[:8])
        from breadmind.core.scheduler import CronJob
        job = CronJob(
            id=job_id, name=data.get("name", ""), schedule=data.get("schedule", ""),
            task=data.get("task", ""), enabled=data.get("enabled", True),
            model=data.get("model"),
        )
        app_state._scheduler.add_cron_job(job)
        # Persist to DB
        if app_state._db:
            try:
                jobs = app_state._scheduler.get_cron_jobs()
                await app_state._db.set_setting("scheduler_cron", jobs)
            except Exception:
                pass
        return {"status": "ok", "job": {"id": job_id, "name": job.name}}

    @r.delete("/api/scheduler/cron/{job_id}")
    async def delete_cron_job(job_id: str):
        if not app_state._scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        removed = app_state._scheduler.remove_cron_job(job_id)
        if app_state._db:
            try:
                await app_state._db.set_setting("scheduler_cron", app_state._scheduler.get_cron_jobs())
            except Exception:
                pass
        return {"status": "ok" if removed else "not_found"}

    @r.get("/api/scheduler/heartbeat")
    async def list_heartbeats():
        if not app_state._scheduler:
            return {"heartbeats": []}
        return {"heartbeats": app_state._scheduler.get_heartbeats()}

    @r.post("/api/scheduler/heartbeat")
    async def add_heartbeat(request: Request):
        if not app_state._scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        data = await request.json()
        import uuid
        hb_id = data.get("id", str(uuid.uuid4())[:8])
        from breadmind.core.scheduler import HeartbeatTask
        hb = HeartbeatTask(
            id=hb_id, name=data.get("name", ""), interval_minutes=data.get("interval_minutes", 30),
            task=data.get("task", ""), enabled=data.get("enabled", True),
        )
        app_state._scheduler.add_heartbeat(hb)
        if app_state._db:
            try:
                await app_state._db.set_setting("scheduler_heartbeat", app_state._scheduler.get_heartbeats())
            except Exception:
                pass
        return {"status": "ok", "heartbeat": {"id": hb_id, "name": hb.name}}

    @r.delete("/api/scheduler/heartbeat/{hb_id}")
    async def delete_heartbeat(hb_id: str):
        if not app_state._scheduler:
            return JSONResponse(status_code=503, content={"error": "Scheduler not configured"})
        removed = app_state._scheduler.remove_heartbeat(hb_id)
        if app_state._db:
            try:
                await app_state._db.set_setting("scheduler_heartbeat", app_state._scheduler.get_heartbeats())
            except Exception:
                pass
        return {"status": "ok" if removed else "not_found"}

    # --- Sub-agent endpoints ---

    @r.post("/api/subagent/spawn")
    async def spawn_subagent(request: Request):
        if not app_state._subagent_manager:
            return JSONResponse(status_code=503, content={"error": "Sub-agent manager not configured"})
        data = await request.json()
        task = await app_state._subagent_manager.spawn(
            task=data.get("task", ""),
            parent_id=data.get("parent_id"),
            model=data.get("model"),
        )
        return {"status": "ok", "task_id": task.id}

    @r.get("/api/subagent/tasks")
    async def list_subagent_tasks():
        if not app_state._subagent_manager:
            return {"tasks": []}
        return {"tasks": app_state._subagent_manager.list_tasks()}

    @r.get("/api/subagent/tasks/{task_id}")
    async def get_subagent_task(task_id: str):
        if not app_state._subagent_manager:
            return JSONResponse(status_code=503, content={"error": "Sub-agent manager not configured"})
        task = app_state._subagent_manager.get_task(task_id)
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})
        return {"task": task}

    @r.get("/api/subagent/status")
    async def subagent_status():
        if not app_state._subagent_manager:
            return {"status": {"total": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0}}
        return {"status": app_state._subagent_manager.get_status()}

    # --- Webhook endpoints ---

    @r.get("/api/webhook/endpoints")
    async def list_webhook_endpoints():
        if not app_state._webhook_manager:
            return {"endpoints": []}
        return {"endpoints": app_state._webhook_manager.get_endpoints()}

    @r.post("/api/webhook/endpoints")
    async def add_webhook_endpoint(request: Request):
        if not app_state._webhook_manager:
            return JSONResponse(status_code=503, content={"error": "Webhook manager not configured"})
        data = await request.json()
        import uuid
        from breadmind.web.webhook import WebhookEndpoint
        ep = WebhookEndpoint(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            path=data.get("path", ""),
            event_type=data.get("event_type", "generic"),
            action=data.get("action", "Webhook received: {payload}"),
            enabled=data.get("enabled", True),
            secret=data.get("secret", ""),
        )
        app_state._webhook_manager.add_endpoint(ep)
        # Persist
        if app_state._db:
            try:
                await app_state._db.set_setting("webhook_endpoints", app_state._webhook_manager.get_endpoints())
            except Exception:
                pass
        return {"status": "ok", "endpoint": {"id": ep.id, "path": ep.path, "url": f"/api/webhook/receive/{ep.path}"}}

    @r.delete("/api/webhook/endpoints/{endpoint_id}")
    async def delete_webhook_endpoint(endpoint_id: str):
        if not app_state._webhook_manager:
            return JSONResponse(status_code=503, content={"error": "Webhook manager not configured"})
        removed = app_state._webhook_manager.remove_endpoint(endpoint_id)
        if app_state._db:
            try:
                await app_state._db.set_setting("webhook_endpoints", app_state._webhook_manager.get_endpoints())
            except Exception:
                pass
        return {"status": "ok" if removed else "not_found"}

    @r.post("/api/webhook/receive/{path:path}")
    async def receive_webhook(path: str, request: Request):
        """Universal webhook receiver -- route to appropriate handler."""
        if not app_state._webhook_manager:
            return JSONResponse(status_code=503, content={"error": "Webhook not configured"})
        try:
            payload = await request.json()
        except Exception:
            payload = {"raw": (await request.body()).decode("utf-8", errors="replace")[:5000]}
        headers = dict(request.headers)
        result = await app_state._webhook_manager.handle_webhook(path, payload, headers)
        if result.get("status") == "not_found":
            return JSONResponse(status_code=404, content=result)
        return result

    @r.get("/api/webhook/log")
    async def webhook_event_log():
        if not app_state._webhook_manager:
            return {"events": []}
        return {"events": app_state._webhook_manager.get_event_log()}

    # --- Container endpoints ---

    @r.get("/api/container/status")
    async def container_status():
        if not app_state._container_executor:
            return {"status": {"docker_available": False, "running_containers": 0, "containers": []}}
        return {"status": app_state._container_executor.get_status()}

    @r.get("/api/container/list")
    async def container_list():
        if not app_state._container_executor:
            return {"containers": []}
        return {"containers": app_state._container_executor.list_containers()}

    @r.post("/api/container/run")
    async def container_run(request: Request):
        if not app_state._container_executor:
            return JSONResponse(status_code=503, content={"error": "Container executor not configured"})
        data = await request.json()
        result = await app_state._container_executor.run_command(
            command=data.get("command", ""),
            image=data.get("image"),
            timeout=data.get("timeout", 30),
            env=data.get("env"),
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "container_id": result.container_id,
            "error": result.error,
        }

    @r.post("/api/container/cleanup")
    async def container_cleanup():
        if not app_state._container_executor:
            return JSONResponse(status_code=503, content={"error": "Container executor not configured"})
        await app_state._container_executor.cleanup()
        return {"status": "ok"}

    # --- Messenger Connection Settings ---

    @r.get("/api/messenger/platforms")
    async def messenger_platforms():
        """Get all messenger platforms with their status and config fields."""
        platforms = {}
        configs = {
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
        }
        token_keys = {
            "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
            "discord": ["DISCORD_BOT_TOKEN"],
            "telegram": ["TELEGRAM_BOT_TOKEN"],
            "whatsapp": ["WHATSAPP_TWILIO_ACCOUNT_SID", "WHATSAPP_TWILIO_AUTH_TOKEN"],
            "gmail": ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"],
            "signal": ["SIGNAL_PHONE_NUMBER"],
        }
        for platform, cfg in configs.items():
            tokens_set = all(bool(os.environ.get(k, "")) for k in token_keys.get(platform, []))
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

    @r.post("/api/messenger/{platform}/token")
    async def set_messenger_token(platform: str, request: Request):
        """Save messenger platform tokens."""
        data = await request.json()
        valid_platforms = {"slack", "discord", "telegram", "whatsapp", "gmail", "signal"}
        if platform not in valid_platforms:
            return JSONResponse(status_code=400, content={"error": f"Invalid platform: {platform}"})

        token_map = {
            "slack": {"bot_token": "SLACK_BOT_TOKEN", "app_token": "SLACK_APP_TOKEN"},
            "discord": {"bot_token": "DISCORD_BOT_TOKEN"},
            "telegram": {"bot_token": "TELEGRAM_BOT_TOKEN"},
            "whatsapp": {"account_sid": "WHATSAPP_TWILIO_ACCOUNT_SID", "auth_token": "WHATSAPP_TWILIO_AUTH_TOKEN", "from_number": "WHATSAPP_FROM_NUMBER"},
            "gmail": {"client_id": "GMAIL_CLIENT_ID", "client_secret": "GMAIL_CLIENT_SECRET", "refresh_token": "GMAIL_REFRESH_TOKEN"},
            "signal": {"phone_number": "SIGNAL_PHONE_NUMBER", "signal_cli_path": "SIGNAL_CLI_PATH"},
        }

        saved = {}
        for field_name, env_key in token_map.get(platform, {}).items():
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

    @r.post("/api/messenger/{platform}/test")
    async def test_messenger(platform: str):
        """Send a test message to verify connection."""
        valid_platforms = {"slack", "discord", "telegram", "whatsapp", "gmail", "signal"}
        if platform not in valid_platforms:
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

    @r.get("/api/messenger/{platform}/setup-url")
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

        return JSONResponse(status_code=400, content={"error": "Invalid platform"})

    @r.get("/api/messenger/slack/oauth-callback")
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

    # --- Additional Messenger endpoints (WhatsApp, Gmail, Signal) ---

    @r.post("/api/webhook/receive/whatsapp")
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

    @r.get("/api/messenger/gmail/oauth-callback")
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
