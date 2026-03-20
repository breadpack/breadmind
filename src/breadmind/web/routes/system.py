"""System routes: setup wizard, auth, health, update, uninstall, webhook."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from breadmind.web.dependencies import (
    get_app_state, get_auth, get_db, get_message_handler, get_monitoring_engine, get_webhook_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


def setup_system_routes(r: APIRouter, app_state):
    """Register system-level routes."""

    # --- Setup wizard endpoints ---

    @r.get("/api/setup/status")
    async def setup_status(db=Depends(get_db)):
        """Check if first-run setup is needed."""
        from breadmind.core.setup_wizard import is_first_run_async
        first_run = await is_first_run_async(db)
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
    async def setup_complete(request: Request, app=Depends(get_app_state)):
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
            if app._db:
                try:
                    from breadmind.config import save_api_key_to_db
                    await save_api_key_to_db(app._db, env_key, api_key)
                except Exception:
                    from breadmind.config import save_env_var
                    save_env_var(env_key, api_key)
            else:
                from breadmind.config import save_env_var
                save_env_var(env_key, api_key)

        # Save provider config
        if not model:
            model = provider_info["models"][0]
        if app._config:
            app._config.llm.default_provider = provider_id
            app._config.llm.default_model = model
        if app._db:
            await app._db.set_setting("llm", {
                "default_provider": provider_id,
                "default_model": model,
                "tool_call_max_turns": app._config.llm.tool_call_max_turns if app._config else 10,
                "tool_call_timeout_seconds": app._config.llm.tool_call_timeout_seconds if app._config else 30,
            })

        # Hot-swap the agent's LLM provider so chat works immediately
        if app._agent and app._config:
            try:
                from breadmind.llm.factory import create_provider
                new_provider = create_provider(app._config)
                await app._agent.update_provider(new_provider)
            except Exception as e:
                logger.warning(f"Failed to hot-swap provider: {e}")

        await mark_setup_complete(app._db)
        return {"status": "ok", "provider": provider_id, "model": model}

    @r.get("/api/setup/discover")
    async def setup_discover(app=Depends(get_app_state)):
        """Discover local infrastructure environment and auto-set specialties."""
        from breadmind.core.setup_wizard import discover_environment
        env = await discover_environment()
        # Auto-set specialties from discovered infra
        specialties = env.detected_specialties()
        if specialties and app._config:
            persona = app._config._persona or {}
            persona["specialties"] = specialties
            app._config._persona = persona
            if app._db:
                try:
                    await app._db.set_setting("persona", persona)
                except Exception:
                    pass
        return {
            "environment": env.to_dict(),
            "summary": env.summary(),
            "specialties": specialties,
        }

    @r.post("/api/setup/recommend")
    async def setup_recommend(app=Depends(get_app_state)):
        """Use LLM to generate setup recommendations based on environment."""
        from breadmind.core.setup_wizard import discover_environment, generate_recommendations

        env = await discover_environment()

        # Create a fresh provider with the newly saved key
        handler = app._message_handler
        try:
            from breadmind.llm.factory import create_provider
            if app._config:
                provider = create_provider(app._config)
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
    async def login(request: Request, auth=Depends(get_auth)):
        """Authenticate with password."""
        if not auth or not auth.enabled:
            return {"status": "ok", "message": "Auth disabled"}
        data = await request.json()
        password = data.get("password", "")
        if auth.verify_password(password):
            token = auth.create_session(
                ip=request.client.host if request.client else "",
                user_agent=request.headers.get("user-agent", ""),
            )
            response = JSONResponse({"status": "ok", "token": token})
            response.set_cookie(
                "breadmind_session", token,
                httponly=True, samesite="strict",
                max_age=auth._session_timeout,
            )
            return response
        return JSONResponse(status_code=401, content={"error": "Invalid password"})

    @r.post("/api/auth/logout")
    async def logout(request: Request, auth=Depends(get_auth)):
        token = request.cookies.get("breadmind_session", "")
        if auth and token:
            auth.revoke_session(token)
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("breadmind_session")
        return response

    @r.get("/api/auth/status")
    async def auth_status(request: Request, auth=Depends(get_auth)):
        if not auth or not auth.enabled:
            return {"auth_enabled": False, "authenticated": True}
        authenticated = auth.authenticate_request(request)
        return {
            "auth_enabled": True,
            "authenticated": authenticated,
            "sessions": auth.get_active_sessions(),
        }

    @r.post("/api/auth/setup")
    async def setup_auth(request: Request, auth=Depends(get_auth), db=Depends(get_db)):
        """Initial password setup (only works when no password is set)."""
        if auth and auth._password_hash:
            return JSONResponse(status_code=403, content={"error": "Password already configured"})
        data = await request.json()
        password = data.get("password", "")
        if len(password) < 8:
            return JSONResponse(status_code=400, content={"error": "Password must be at least 8 characters"})
        from breadmind.web.auth import AuthManager
        pw_hash = AuthManager.hash_password(password)
        if auth:
            auth._password_hash = pw_hash
            auth._enabled = True
        # Persist to DB
        if db:
            try:
                await db.set_setting("auth", {"password_hash": pw_hash, "enabled": True})
            except Exception:
                pass
        token = auth.create_session() if auth else ""
        response = JSONResponse({"status": "ok", "message": "Password set successfully"})
        if token:
            response.set_cookie("breadmind_session", token, httponly=True, samesite="strict")
        return response

    # --- Health endpoint ---

    @r.get("/health")
    async def health(
        message_handler=Depends(get_message_handler),
        monitoring_engine=Depends(get_monitoring_engine),
    ):
        agent_ok = message_handler is not None
        monitoring_ok = (
            monitoring_engine is not None
            and monitoring_engine.get_status()["running"]
        ) if monitoring_engine is not None else False

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
        """Check for new version from GitHub Releases."""
        import aiohttp
        try:
            from importlib.metadata import version as pkg_version
            current = pkg_version("breadmind")
        except Exception:
            current = "0.0.0"

        latest = current
        update_available = False
        release_notes = ""

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

        # Version comparison
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
        """Apply update. Tries git pull first (dev mode), then pip install."""
        try:
            # Strategy 1: git pull (dev/editable install)
            import breadmind
            pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(breadmind.__file__)))
            git_dir = os.path.join(os.path.dirname(pkg_dir), ".git")
            if os.path.isdir(git_dir):
                repo_dir = os.path.dirname(pkg_dir)
                proc = await asyncio.create_subprocess_exec(
                    "git", "pull", "origin", "master",
                    cwd=repo_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                output = stdout.decode("utf-8", errors="replace")
                if proc.returncode == 0:
                    return {
                        "status": "ok",
                        "message": "Updated via git pull. Restart the service to apply.",
                        "output": output[-500:],
                        "restart_required": True,
                    }

            # Strategy 2: pip install --upgrade breadmind (PyPI)
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
                    "message": "Update installed via pip. Restart the service to apply.",
                    "output": output[-500:],
                    "restart_required": True,
                }

            # Strategy 3: pip install from GitHub
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
                "message": "Update failed. Try manually: git pull or pip install --upgrade breadmind",
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
                remove_service_files, remove_config,
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

    # --- Webhook endpoints ---

    @r.get("/api/webhook/endpoints")
    async def list_webhook_endpoints(webhook_manager=Depends(get_webhook_manager)):
        if not webhook_manager:
            return {"endpoints": []}
        return {"endpoints": webhook_manager.get_endpoints()}

    @r.post("/api/webhook/endpoints")
    async def add_webhook_endpoint(
        request: Request,
        webhook_manager=Depends(get_webhook_manager),
        db=Depends(get_db),
    ):
        if not webhook_manager:
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
        webhook_manager.add_endpoint(ep)
        # Persist
        if db:
            try:
                await db.set_setting("webhook_endpoints", webhook_manager.get_endpoints())
            except Exception:
                pass
        return {"status": "ok", "endpoint": {"id": ep.id, "path": ep.path, "url": f"/api/webhook/receive/{ep.path}"}}

    @r.delete("/api/webhook/endpoints/{endpoint_id}")
    async def delete_webhook_endpoint(
        endpoint_id: str,
        webhook_manager=Depends(get_webhook_manager),
        db=Depends(get_db),
    ):
        if not webhook_manager:
            return JSONResponse(status_code=503, content={"error": "Webhook manager not configured"})
        removed = webhook_manager.remove_endpoint(endpoint_id)
        if db:
            try:
                await db.set_setting("webhook_endpoints", webhook_manager.get_endpoints())
            except Exception:
                pass
        return {"status": "ok" if removed else "not_found"}

    @r.post("/api/webhook/receive/{path:path}")
    async def receive_webhook(path: str, request: Request, webhook_manager=Depends(get_webhook_manager)):
        """Universal webhook receiver -- route to appropriate handler."""
        if not webhook_manager:
            return JSONResponse(status_code=503, content={"error": "Webhook not configured"})
        try:
            payload = await request.json()
        except Exception:
            payload = {"raw": (await request.body()).decode("utf-8", errors="replace")[:5000]}
        headers = dict(request.headers)
        result = await webhook_manager.handle_webhook(path, payload, headers)
        if result.get("status") == "not_found":
            return JSONResponse(status_code=404, content=result)
        return result

    @r.get("/api/webhook/log")
    async def webhook_event_log(webhook_manager=Depends(get_webhook_manager)):
        if not webhook_manager:
            return {"events": []}
        return {"events": webhook_manager.get_event_log()}
