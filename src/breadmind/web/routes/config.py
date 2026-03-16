"""Configuration management routes."""
from __future__ import annotations

import logging
import os
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


def setup_config_routes(r: APIRouter, app_state):
    """Register all /api/config/* routes."""

    @r.get("/api/config")
    async def get_config():
        if app_state._config:
            return {
                "llm": {
                    "default_provider": app_state._config.llm.default_provider,
                    "default_model": app_state._config.llm.default_model,
                    "tool_call_max_turns": app_state._config.llm.tool_call_max_turns,
                    "tool_call_timeout_seconds": app_state._config.llm.tool_call_timeout_seconds,
                },
                "mcp": {
                    "auto_discover": app_state._config.mcp.auto_discover,
                    "max_restart_attempts": app_state._config.mcp.max_restart_attempts,
                    "servers": app_state._config.mcp.servers,
                    "registries": [
                        {"name": r.name, "type": r.type, "enabled": r.enabled}
                        for r in app_state._config.mcp.registries
                    ],
                },
                "database": {
                    "host": app_state._config.database.host,
                    "port": app_state._config.database.port,
                    "name": app_state._config.database.name,
                },
            }
        return {}

    @r.get("/api/safety")
    async def get_safety():
        if app_state._safety_config:
            return app_state._safety_config
        return {"blacklist": {}, "require_approval": []}

    @r.get("/api/config/safety")
    async def get_safety_config():
        """Get editable safety configuration."""
        if app_state._safety_guard and hasattr(app_state._safety_guard, 'get_config'):
            return {"safety": app_state._safety_guard.get_config()}
        # Fallback to raw config
        if app_state._safety_config:
            return {"safety": app_state._safety_config}
        return {"safety": {"blacklist": {}, "require_approval": [], "user_permissions": {}, "admin_users": []}}

    @r.post("/api/config/safety/blacklist")
    async def update_blacklist(request: Request):
        """Update safety blacklist."""
        data = await request.json()
        blacklist = data.get("blacklist", {})
        if not isinstance(blacklist, dict):
            return JSONResponse(status_code=400, content={"error": "blacklist must be a dict"})
        if app_state._safety_guard:
            app_state._safety_guard.update_blacklist(blacklist)
        # Persist to DB
        if app_state._db:
            await app_state._db.set_setting("safety_blacklist", blacklist)
        return {"status": "ok"}

    @r.post("/api/config/safety/approval")
    async def update_require_approval(request: Request):
        """Update require_approval list."""
        data = await request.json()
        tools = data.get("require_approval", [])
        if app_state._safety_guard:
            app_state._safety_guard.update_require_approval(tools)
        if app_state._db:
            await app_state._db.set_setting("safety_approval", tools)
        return {"status": "ok"}

    @r.post("/api/config/safety/permissions")
    async def update_permissions(request: Request):
        """Update user permissions and admin list."""
        data = await request.json()
        permissions = data.get("user_permissions", {})
        admins = data.get("admin_users", [])
        if app_state._safety_guard:
            app_state._safety_guard.update_user_permissions(permissions, admins)
        if app_state._db:
            await app_state._db.set_setting("safety_permissions", {"user_permissions": permissions, "admin_users": admins})
        return {"status": "ok"}

    # -- Skill Market Management --

    @r.get("/api/config/markets")
    async def get_markets():
        """Get configured skill markets/registries."""
        if not app_state._search_engine:
            return {"markets": []}
        return {
            "markets": [
                {"name": reg.name, "type": reg.type, "enabled": reg.enabled, "url": reg.url or ""}
                for reg in app_state._search_engine.get_registries()
            ]
        }

    @r.post("/api/config/markets")
    async def update_markets(request: Request):
        """Add or update a skill market."""
        data = await request.json()
        if not app_state._search_engine:
            return {"status": "error", "error": "Search engine not available"}
        from breadmind.tools.registry_search import RegistryConfig
        config = RegistryConfig(
            name=data.get("name", ""),
            type=data.get("type", "skills_sh"),
            enabled=data.get("enabled", True),
            url=data.get("url", ""),
        )
        if not config.name:
            return {"status": "error", "error": "name is required"}
        app_state._search_engine.add_registry(config)
        # Persist
        if app_state._db:
            markets = [
                {"name": reg.name, "type": reg.type, "enabled": reg.enabled, "url": reg.url or ""}
                for reg in app_state._search_engine.get_registries()
            ]
            await app_state._db.set_setting("skill_markets", markets)
        return {"status": "ok"}

    @r.post("/api/config/markets/toggle")
    async def toggle_market(request: Request):
        """Enable/disable a skill market."""
        data = await request.json()
        name = data.get("name", "")
        enabled = data.get("enabled", True)
        if app_state._search_engine:
            app_state._search_engine.toggle_registry(name, enabled)
            if app_state._db:
                markets = [
                    {"name": reg.name, "type": reg.type, "enabled": reg.enabled, "url": reg.url or ""}
                    for reg in app_state._search_engine.get_registries()
                ]
                await app_state._db.set_setting("skill_markets", markets)
        return {"status": "ok"}

    @r.delete("/api/config/markets/{name}")
    async def delete_market(name: str):
        """Remove a skill market."""
        if app_state._search_engine:
            app_state._search_engine.remove_registry(name)
            if app_state._db:
                markets = [
                    {"name": reg.name, "type": reg.type, "enabled": reg.enabled, "url": reg.url or ""}
                    for reg in app_state._search_engine.get_registries()
                ]
                await app_state._db.set_setting("skill_markets", markets)
        return {"status": "ok"}

    @r.get("/api/config/api-keys")
    async def get_api_keys_status():
        """Return which API keys are set (masked values)."""
        keys = {}
        for key_name in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"]:
            val = os.environ.get(key_name, "")
            if val:
                keys[key_name] = {"set": True, "masked": val[:8] + "***" if len(val) > 8 else "***"}
            else:
                keys[key_name] = {"set": False, "masked": ""}
        return {"keys": keys}

    async def _validate_api_key(key_name: str, value: str) -> dict:
        """Validate an API key using the unified validator."""
        from breadmind.core.setup_wizard import validate_api_key
        result = await validate_api_key(key_name, value)
        # Normalize field name for backward compat
        return {"valid": result.get("valid", False), "reason": result.get("error", "")}

    @r.post("/api/config/api-keys")
    async def update_api_key(request: Request):
        """Update an API key -- encrypted in DB, or fallback to .env."""
        from breadmind.config import _VALID_API_KEY_NAMES, save_api_key_to_db
        data = await request.json()
        key_name = data.get("key_name", "")
        value = data.get("value", "")
        if key_name not in _VALID_API_KEY_NAMES:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid key name. Must be one of {list(_VALID_API_KEY_NAMES)}"},
            )
        if not value:
            return JSONResponse(
                status_code=400,
                content={"error": "API key value cannot be empty"},
            )

        # Validate key by making a lightweight API call
        validation = await _validate_api_key(key_name, value)
        if not validation["valid"]:
            return JSONResponse(
                status_code=400,
                content={"error": f"API key validation failed: {validation['reason']}"},
            )

        persisted_to = "memory"
        if app_state._db:
            try:
                await save_api_key_to_db(app_state._db, key_name, value)
                persisted_to = "db_encrypted"
            except Exception as e:
                logger.warning(f"Failed to save API key to DB: {e}")
                # Fallback: set in runtime only
                os.environ[key_name] = value
        else:
            # No DB -- save to .env as fallback
            from breadmind.config import save_env_var
            save_env_var(key_name, value)
            persisted_to = "env_file"

        masked = value[:8] + "***" if len(value) > 8 else "***"
        return {"status": "ok", "masked": masked, "storage": persisted_to}

    @r.post("/api/config/provider")
    async def update_provider(request: Request):
        """Update LLM provider settings."""
        from breadmind.config import _VALID_PROVIDERS
        data = await request.json()
        provider = data.get("provider")
        model = data.get("model")
        max_turns = data.get("max_turns")
        timeout = data.get("timeout")

        if provider is not None:
            if provider not in _VALID_PROVIDERS:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Invalid provider. Must be one of {list(_VALID_PROVIDERS)}"},
                )
            if app_state._config:
                app_state._config.llm.default_provider = provider

        if model is not None:
            if app_state._config:
                app_state._config.llm.default_model = model

        if max_turns is not None:
            try:
                max_turns = int(max_turns)
                if max_turns < 1:
                    raise ValueError()
            except (ValueError, TypeError):
                return JSONResponse(
                    status_code=400,
                    content={"error": "max_turns must be a positive integer"},
                )
            if app_state._config:
                app_state._config.llm.tool_call_max_turns = max_turns

        if timeout is not None:
            try:
                timeout = int(timeout)
                if timeout < 1:
                    raise ValueError()
            except (ValueError, TypeError):
                return JSONResponse(
                    status_code=400,
                    content={"error": "timeout must be a positive integer"},
                )
            if app_state._config:
                app_state._config.llm.tool_call_timeout_seconds = timeout

        # Persist to DB
        if app_state._db and app_state._config:
            try:
                await app_state._db.set_setting("llm", {
                    "default_provider": app_state._config.llm.default_provider,
                    "default_model": app_state._config.llm.default_model,
                    "tool_call_max_turns": app_state._config.llm.tool_call_max_turns,
                    "tool_call_timeout_seconds": app_state._config.llm.tool_call_timeout_seconds,
                })
            except Exception as e:
                logger.warning(f"Failed to persist LLM settings to DB: {e}")

        # Hot-swap agent provider and sync settings
        if app_state._agent and app_state._config:
            if provider is not None or model is not None:
                try:
                    from breadmind.llm.factory import create_provider as _create_provider
                    new_provider = _create_provider(app_state._config)
                    await app_state._agent.update_provider(new_provider)
                except Exception as e:
                    logger.warning(f"Failed to hot-swap provider: {e}")
            if max_turns is not None:
                app_state._agent.update_max_turns(app_state._config.llm.tool_call_max_turns)
            if timeout is not None:
                app_state._agent.update_timeouts(tool_timeout=app_state._config.llm.tool_call_timeout_seconds)

        return {"status": "ok", "persisted": app_state._db is not None}

    @r.get("/api/config/models/{provider}")
    async def list_provider_models(provider: str):
        """Fetch available models from a provider's API."""
        import aiohttp
        models = []
        try:
            if provider == "claude":
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if api_key:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://api.anthropic.com/v1/models",
                            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                models = [m["id"] for m in data.get("data", [])]
                if not models:
                    models = ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6",
                              "claude-sonnet-4-5-20250514", "claude-3-5-haiku-20241022"]

            elif provider == "gemini":
                api_key = os.environ.get("GEMINI_API_KEY", "")
                if api_key:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                models = [m["name"].replace("models/", "") for m in data.get("models", [])
                                          if "generateContent" in m.get("supportedGenerationMethods", [])]
                if not models:
                    models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
                              "gemini-1.5-flash", "gemini-1.5-pro"]

            elif provider == "openai":
                api_key = os.environ.get("OPENAI_API_KEY", "")
                if api_key:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://api.openai.com/v1/models",
                            headers={"Authorization": f"Bearer {api_key}"},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                models = sorted([m["id"] for m in data.get("data", [])
                                                 if "gpt" in m["id"] or "o1" in m["id"] or "o3" in m["id"]])
                if not models:
                    models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3-mini"]

            elif provider == "grok":
                api_key = os.environ.get("XAI_API_KEY", "")
                if api_key:
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                "https://api.x.ai/v1/models",
                                headers={"Authorization": f"Bearer {api_key}"},
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    models = [m["id"] for m in data.get("data", [])]
                    except Exception:
                        pass
                if not models:
                    models = ["grok-3", "grok-3-mini", "grok-2"]

            elif provider == "ollama":
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "http://localhost:11434/api/tags",
                            timeout=aiohttp.ClientTimeout(total=5),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                models = [m["name"] for m in data.get("models", [])]
                except Exception:
                    pass
                if not models:
                    models = ["llama3.1", "mistral", "codellama", "qwen2.5"]

            elif provider == "cli":
                models = ["claude -p", "gemini", "codex"]

        except Exception as e:
            logger.warning(f"Failed to fetch models for {provider}: {e}")

        return {"provider": provider, "models": models}

    @r.post("/api/config/mcp")
    async def update_mcp(request: Request):
        """Update MCP configuration."""
        data = await request.json()
        auto_discover = data.get("auto_discover")
        max_restart = data.get("max_restart_attempts")

        if app_state._config:
            if auto_discover is not None:
                app_state._config.mcp.auto_discover = bool(auto_discover)
            if max_restart is not None:
                try:
                    max_restart = int(max_restart)
                    if max_restart < 0:
                        raise ValueError()
                except (ValueError, TypeError):
                    return JSONResponse(
                        status_code=400,
                        content={"error": "max_restart_attempts must be a non-negative integer"},
                    )
                app_state._config.mcp.max_restart_attempts = max_restart

        # Persist to DB
        if app_state._db and app_state._config:
            try:
                await app_state._db.set_setting("mcp", {
                    "auto_discover": app_state._config.mcp.auto_discover,
                    "max_restart_attempts": app_state._config.mcp.max_restart_attempts,
                })
            except Exception as e:
                logger.warning(f"Failed to persist MCP settings to DB: {e}")

        return {"status": "ok", "persisted": app_state._db is not None}

    @r.get("/api/config/persona")
    async def get_persona():
        """Get current persona settings."""
        from breadmind.config import DEFAULT_PERSONA, DEFAULT_PERSONA_PRESETS
        if app_state._config and hasattr(app_state._config, '_persona') and app_state._config._persona:
            persona = app_state._config._persona
        else:
            persona = DEFAULT_PERSONA
        return {"persona": persona, "presets": list(DEFAULT_PERSONA_PRESETS.keys())}

    @r.post("/api/config/persona")
    async def update_persona(request: Request):
        """Update persona settings."""
        from breadmind.config import DEFAULT_PERSONA_PRESETS, DEFAULT_PERSONA, build_system_prompt
        data = await request.json()

        # Build persona from input
        persona = {}
        persona["name"] = data.get("name", "BreadMind").strip() or "BreadMind"
        persona["preset"] = data.get("preset", "professional")
        persona["language"] = data.get("language", "ko")
        persona["specialties"] = data.get("specialties", ["kubernetes", "proxmox", "openwrt"])

        # If preset changed, use preset prompt; otherwise use custom
        custom_prompt = data.get("system_prompt", "")
        if custom_prompt:
            persona["system_prompt"] = custom_prompt
        elif persona["preset"] in DEFAULT_PERSONA_PRESETS:
            persona["system_prompt"] = DEFAULT_PERSONA_PRESETS[persona["preset"]]
        else:
            persona["system_prompt"] = DEFAULT_PERSONA_PRESETS["professional"]

        # Apply to runtime
        if app_state._config:
            app_state._config._persona = persona
        if app_state._agent and hasattr(app_state._agent, 'set_persona'):
            app_state._agent.set_persona(persona)

        # Persist to DB
        if app_state._db:
            try:
                await app_state._db.set_setting("persona", persona)
            except Exception as e:
                logger.warning(f"Failed to persist persona to DB: {e}")

        return {"status": "ok", "persona": persona}

    @r.get("/api/config/settings-status")
    async def get_settings_status():
        """Check if settings are DB-persisted."""
        return {"db_connected": app_state._db is not None}

    # --- Prompt management ---

    @r.get("/api/config/prompts")
    async def get_prompts():
        """Get all configurable prompts."""
        from breadmind.core.swarm import DEFAULT_ROLES
        from breadmind.mcp.install_assistant import INSTALL_SYSTEM_PROMPT, ANALYZE_PROMPT, TROUBLESHOOT_PROMPT

        # Load custom overrides from DB
        custom = {}
        if app_state._db:
            try:
                saved = await app_state._db.get_setting("custom_prompts")
                if saved:
                    custom = saved
            except Exception:
                pass

        roles = {}
        for name, member in DEFAULT_ROLES.items():
            roles[name] = {
                "description": member.description,
                "system_prompt": custom.get(f"swarm_role:{name}", member.system_prompt),
                "is_custom": f"swarm_role:{name}" in custom,
            }

        # Behavior prompt (from dedicated DB key, not custom_prompts)
        from breadmind.config import _PROACTIVE_BEHAVIOR_PROMPT
        behavior_prompt = _PROACTIVE_BEHAVIOR_PROMPT
        if app_state._agent and hasattr(app_state._agent, 'get_behavior_prompt'):
            behavior_prompt = app_state._agent.get_behavior_prompt()

        return {
            "main_system_prompt": custom.get("main_system_prompt", ""),
            "behavior_prompt": behavior_prompt,
            "behavior_prompt_default": _PROACTIVE_BEHAVIOR_PROMPT,
            "swarm_roles": roles,
            "swarm_decompose": custom.get("swarm_decompose", ""),
            "swarm_aggregate": custom.get("swarm_aggregate", ""),
            "mcp_install": custom.get("mcp_install", INSTALL_SYSTEM_PROMPT),
            "mcp_analyze": custom.get("mcp_analyze", ANALYZE_PROMPT),
            "mcp_troubleshoot": custom.get("mcp_troubleshoot", TROUBLESHOOT_PROMPT),
            "setup_recommend": custom.get("setup_recommend", ""),
        }

    @r.post("/api/config/prompts")
    async def update_prompts(request: Request):
        """Update custom prompts. Empty string = use default."""
        data = await request.json()

        # Load existing
        custom = {}
        if app_state._db:
            try:
                saved = await app_state._db.get_setting("custom_prompts")
                if saved:
                    custom = saved
            except Exception:
                pass

        # Update only provided keys
        valid_keys = [
            "main_system_prompt", "swarm_decompose", "swarm_aggregate",
            "mcp_install", "mcp_analyze", "mcp_troubleshoot", "setup_recommend",
        ]
        for key in valid_keys:
            if key in data:
                if data[key]:  # non-empty = custom
                    custom[key] = data[key]
                else:  # empty = reset to default
                    custom.pop(key, None)

        # Swarm role prompts -- update SwarmManager directly
        for role_name, prompt in data.get("swarm_roles", {}).items():
            if app_state._swarm_manager and prompt:
                app_state._swarm_manager.update_role(role_name, system_prompt=prompt)
            role_key = f"swarm_role:{role_name}"
            if prompt:
                custom[role_key] = prompt
            else:
                custom.pop(role_key, None)

        # Apply main system prompt to agent
        if "main_system_prompt" in data and data["main_system_prompt"] and app_state._agent:
            app_state._agent.set_system_prompt(data["main_system_prompt"])

        # Apply behavior prompt to agent
        if "behavior_prompt" in data and app_state._agent:
            from breadmind.config import _PROACTIVE_BEHAVIOR_PROMPT
            new_bp = data["behavior_prompt"].strip()
            if new_bp:
                app_state._agent.set_behavior_prompt(new_bp)
            else:
                # Empty = reset to default
                app_state._agent.set_behavior_prompt(_PROACTIVE_BEHAVIOR_PROMPT)
                new_bp = _PROACTIVE_BEHAVIOR_PROMPT
            # Persist behavior prompt separately
            if app_state._db:
                from datetime import datetime, timezone
                await app_state._db.set_setting("behavior_prompt", {
                    "prompt": new_bp,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "reason": "manual edit via Settings UI",
                })

        # Persist
        if app_state._db:
            await app_state._db.set_setting("custom_prompts", custom)

        # Persist swarm roles if updated
        if data.get("swarm_roles") and app_state._swarm_manager:
            await app_state._persist_swarm_roles()

        return {"status": "ok"}

    # --- Monitoring Rules (config section) ---

    @r.get("/api/config/monitoring/rules")
    async def get_monitoring_rules():
        if app_state._monitoring_engine and hasattr(app_state._monitoring_engine, 'get_rules_config'):
            rules = app_state._monitoring_engine.get_rules_config()
            lp = app_state._monitoring_engine.get_loop_protector_config()
            return {"rules": rules, "loop_protector": lp}
        return {"rules": [], "loop_protector": {}}

    @r.post("/api/config/monitoring/rules")
    async def update_monitoring_rules(request: Request):
        data = await request.json()
        if not app_state._monitoring_engine:
            return JSONResponse(status_code=503, content={"error": "Monitoring not configured"})
        # Update individual rules
        for rule_update in data.get("rules", []):
            name = rule_update.get("name")
            if "enabled" in rule_update:
                if rule_update["enabled"]:
                    app_state._monitoring_engine.enable_rule(name)
                else:
                    app_state._monitoring_engine.disable_rule(name)
            if "interval_seconds" in rule_update:
                app_state._monitoring_engine.update_rule_interval(name, rule_update["interval_seconds"])
        # Update loop protector
        lp = data.get("loop_protector", {})
        if lp:
            app_state._monitoring_engine.update_loop_protector_config(
                cooldown_minutes=lp.get("cooldown_minutes"),
                max_auto_actions=lp.get("max_auto_actions"),
            )
        if app_state._db:
            try:
                await app_state._db.set_setting("monitoring_config", data)
            except Exception:
                pass
        return {"status": "ok"}

    # --- Messenger Config ---

    @r.get("/api/config/messenger")
    async def get_messenger_config():
        if app_state._message_router and hasattr(app_state._message_router, 'get_allowed_users'):
            return {"allowed_users": app_state._message_router.get_allowed_users()}
        return {"allowed_users": {"slack": [], "discord": [], "telegram": []}}

    @r.post("/api/config/messenger")
    async def update_messenger_config(request: Request):
        data = await request.json()
        if not app_state._message_router:
            return JSONResponse(status_code=503, content={"error": "Messenger not configured"})
        for platform, users in data.get("allowed_users", {}).items():
            app_state._message_router.update_allowed_users(platform, users)
        if app_state._db:
            try:
                await app_state._db.set_setting("messenger_config", data.get("allowed_users", {}))
            except Exception:
                pass
        return {"status": "ok"}

    # --- Memory Config ---

    @r.get("/api/config/memory")
    async def get_memory_config():
        if app_state._working_memory and hasattr(app_state._working_memory, 'get_config'):
            return {"memory": app_state._working_memory.get_config()}
        return {"memory": {"max_messages_per_session": 50, "session_timeout_minutes": 30, "active_sessions": 0}}

    @r.post("/api/config/memory")
    async def update_memory_config(request: Request):
        data = await request.json()
        if app_state._working_memory:
            app_state._working_memory.update_config(
                max_messages=data.get("max_messages"),
                timeout_minutes=data.get("timeout_minutes"),
            )
        if app_state._db:
            try:
                await app_state._db.set_setting("memory_config", data)
            except Exception:
                pass
        return {"status": "ok"}

    # --- Tool Security ---

    @r.get("/api/config/tool-security")
    async def get_tool_security():
        from breadmind.tools.builtin import ToolSecurityConfig
        return {"security": ToolSecurityConfig.get_config()}

    @r.post("/api/config/tool-security")
    async def update_tool_security(request: Request):
        from breadmind.tools.builtin import ToolSecurityConfig
        data = await request.json()
        ToolSecurityConfig.update(
            dangerous_patterns=data.get("dangerous_patterns"),
            sensitive_patterns=data.get("sensitive_patterns"),
            allowed_ssh_hosts=data.get("allowed_ssh_hosts"),
            base_directory=data.get("base_directory"),
        )
        if app_state._db:
            try:
                await app_state._db.set_setting("tool_security", ToolSecurityConfig.get_config())
            except Exception:
                pass
        return {"status": "ok"}

    # --- Agent Timeouts ---

    @r.get("/api/config/timeouts")
    async def get_timeouts():
        if app_state._agent and hasattr(app_state._agent, 'get_timeouts'):
            return {"timeouts": app_state._agent.get_timeouts()}
        return {"timeouts": {"tool_timeout": 30, "chat_timeout": 120, "max_turns": 10}}

    @r.post("/api/config/timeouts")
    async def update_timeouts(request: Request):
        data = await request.json()
        if app_state._agent:
            if hasattr(app_state._agent, 'update_timeouts'):
                app_state._agent.update_timeouts(
                    tool_timeout=data.get("tool_timeout"),
                    chat_timeout=data.get("chat_timeout"),
                )
            if "max_turns" in data and hasattr(app_state._agent, 'update_max_turns'):
                app_state._agent.update_max_turns(data["max_turns"])
        if app_state._db:
            try:
                await app_state._db.set_setting("agent_timeouts", data)
            except Exception:
                pass
        return {"status": "ok"}

    # --- Logging Level ---

    @r.post("/api/config/logging")
    async def update_logging(request: Request):
        import logging as _logging
        data = await request.json()
        level = data.get("level", "INFO").upper()
        valid = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if level not in valid:
            return JSONResponse(status_code=400, content={"error": f"Invalid level. Must be one of {valid}"})
        _logging.getLogger().setLevel(getattr(_logging, level))
        if app_state._config:
            app_state._config.logging.level = level
        if app_state._db:
            try:
                await app_state._db.set_setting("logging_config", {"level": level})
            except Exception:
                pass
        return {"status": "ok", "level": level}
