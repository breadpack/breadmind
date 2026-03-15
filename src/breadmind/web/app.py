import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Callable, Any

logger = logging.getLogger(__name__)

class WebApp:
    def __init__(self, message_handler: Callable | None = None, tool_registry=None, mcp_manager=None,
                 config=None, monitoring_engine=None, safety_config=None,
                 agent=None, audit_logger=None, metrics_collector=None, database=None,
                 mcp_store=None, safety_guard=None, working_memory=None, message_router=None):
        self.app = FastAPI(title="BreadMind", version="0.1.0")
        self._message_handler = message_handler
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._config = config
        self._monitoring_engine = monitoring_engine
        self._safety_config = safety_config
        self._agent = agent
        self._audit_logger = audit_logger
        self._metrics_collector = metrics_collector
        self._db = database
        self._mcp_store = mcp_store
        self._safety_guard = safety_guard
        self._working_memory = working_memory
        self._message_router = message_router
        self._connections: list[WebSocket] = []
        self._events: list[dict] = []
        self._lock = asyncio.Lock()
        self._setup_routes()

    async def on_monitoring_event(self, event):
        """Called by monitoring engine when an event occurs."""
        event_dict = {
            "source": event.source,
            "target": event.target,
            "severity": event.severity,
            "condition": event.condition,
            "details": event.details,
            "timestamp": event.timestamp.isoformat(),
        }
        self._events.append(event_dict)
        # Keep last 100 events
        if len(self._events) > 100:
            self._events = self._events[-100:]
        # Broadcast to connected WebSocket clients
        await self.broadcast_event(event_dict)

    async def broadcast_event(self, event_dict):
        async with self._lock:
            connections = self._connections[:]
        for ws in connections:
            try:
                await ws.send_text(json.dumps({"type": "monitoring_event", "event": event_dict}))
            except Exception:
                async with self._lock:
                    if ws in self._connections:
                        self._connections.remove(ws)

    def _setup_routes(self):
        app = self.app

        @app.get("/health")
        async def health():
            agent_ok = self._message_handler is not None
            monitoring_ok = (
                self._monitoring_engine is not None
                and self._monitoring_engine.get_status()["running"]
            ) if self._monitoring_engine is not None else False

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

        @app.get("/api/tools")
        async def list_tools():
            if self._tool_registry:
                defs = self._tool_registry.get_all_definitions()
                return {"tools": [
                    {"name": d.name, "description": d.description, "source": self._tool_registry.get_tool_source(d.name)}
                    for d in defs
                ]}
            return {"tools": []}

        @app.get("/api/mcp/servers")
        async def list_mcp_servers():
            if self._mcp_manager:
                servers = await self._mcp_manager.list_servers()
                return {"servers": [
                    {"name": s.name, "transport": s.transport, "status": s.status, "tools": s.tools, "source": s.source}
                    for s in servers
                ]}
            return {"servers": []}

        @app.get("/", response_class=HTMLResponse)
        async def index():
            html_path = Path(__file__).parent / "static" / "index.html"
            if html_path.exists():
                return html_path.read_text(encoding="utf-8")
            return "<html><body><h1>BreadMind</h1><p>Static files not found.</p></body></html>"

        @app.get("/api/config")
        async def get_config():
            if self._config:
                return {
                    "llm": {
                        "default_provider": self._config.llm.default_provider,
                        "default_model": self._config.llm.default_model,
                        "tool_call_max_turns": self._config.llm.tool_call_max_turns,
                        "tool_call_timeout_seconds": self._config.llm.tool_call_timeout_seconds,
                    },
                    "mcp": {
                        "auto_discover": self._config.mcp.auto_discover,
                        "max_restart_attempts": self._config.mcp.max_restart_attempts,
                        "servers": self._config.mcp.servers,
                        "registries": [
                            {"name": r.name, "type": r.type, "enabled": r.enabled}
                            for r in self._config.mcp.registries
                        ],
                    },
                    "database": {
                        "host": self._config.database.host,
                        "port": self._config.database.port,
                        "name": self._config.database.name,
                    },
                }
            return {}

        @app.get("/api/safety")
        async def get_safety():
            if self._safety_config:
                return self._safety_config
            return {"blacklist": {}, "require_approval": []}

        @app.get("/api/config/safety")
        async def get_safety_config():
            """Get editable safety configuration."""
            if self._safety_guard and hasattr(self._safety_guard, 'get_config'):
                return {"safety": self._safety_guard.get_config()}
            # Fallback to raw config
            if self._safety_config:
                return {"safety": self._safety_config}
            return {"safety": {"blacklist": {}, "require_approval": [], "user_permissions": {}, "admin_users": []}}

        @app.post("/api/config/safety/blacklist")
        async def update_blacklist(request: Request):
            """Update safety blacklist."""
            data = await request.json()
            blacklist = data.get("blacklist", {})
            if not isinstance(blacklist, dict):
                return JSONResponse(status_code=400, content={"error": "blacklist must be a dict"})
            if self._safety_guard:
                self._safety_guard.update_blacklist(blacklist)
            # Persist to DB
            if self._db:
                await self._db.set_setting("safety_blacklist", blacklist)
            return {"status": "ok"}

        @app.post("/api/config/safety/approval")
        async def update_require_approval(request: Request):
            """Update require_approval list."""
            data = await request.json()
            tools = data.get("require_approval", [])
            if self._safety_guard:
                self._safety_guard.update_require_approval(tools)
            if self._db:
                await self._db.set_setting("safety_approval", tools)
            return {"status": "ok"}

        @app.post("/api/config/safety/permissions")
        async def update_permissions(request: Request):
            """Update user permissions and admin list."""
            data = await request.json()
            permissions = data.get("user_permissions", {})
            admins = data.get("admin_users", [])
            if self._safety_guard:
                self._safety_guard.update_user_permissions(permissions, admins)
            if self._db:
                await self._db.set_setting("safety_permissions", {"user_permissions": permissions, "admin_users": admins})
            return {"status": "ok"}

        @app.get("/api/monitoring/events")
        async def get_monitoring_events():
            return {"events": self._events[-50:]}

        @app.get("/api/monitoring/status")
        async def get_monitoring_status():
            if self._monitoring_engine:
                status = self._monitoring_engine.get_status()
                return {
                    "running": status["running"],
                    "rules": status["rules_count"],
                    "events_total": len(self._events),
                }
            return {"running": False, "rules": 0, "events_total": 0}

        @app.get("/api/usage")
        async def get_usage():
            """Return token usage and cost stats from agent."""
            if self._agent and hasattr(self._agent, 'get_usage'):
                usage = self._agent.get_usage()
                return {"usage": usage}
            return {"usage": {}}

        @app.get("/api/audit")
        async def get_audit():
            """Return recent audit log entries."""
            if self._audit_logger and hasattr(self._audit_logger, 'get_recent'):
                entries = self._audit_logger.get_recent(50)
                serialized = []
                for e in entries:
                    if hasattr(e, '__dataclass_fields__'):
                        serialized.append(asdict(e))
                    elif isinstance(e, dict):
                        serialized.append(e)
                    else:
                        serialized.append(str(e))
                return {"entries": serialized}
            return {"entries": []}

        @app.get("/api/metrics")
        async def get_metrics():
            """Return tool execution metrics."""
            if self._metrics_collector and hasattr(self._metrics_collector, 'get_summary'):
                return {"metrics": self._metrics_collector.get_summary()}
            return {"metrics": {}}

        @app.get("/api/approvals")
        async def get_approvals():
            """Return pending approval requests."""
            if self._agent and hasattr(self._agent, 'get_pending_approvals'):
                return {"approvals": self._agent.get_pending_approvals()}
            return {"approvals": []}

        @app.post("/api/approvals/{approval_id}/approve")
        async def approve_tool(approval_id: str):
            """Approve a pending tool execution."""
            if self._agent and hasattr(self._agent, 'approve_tool'):
                result = self._agent.approve_tool(approval_id)
                return {"status": "approved", "approval_id": approval_id, "result": result}
            return JSONResponse(
                status_code=404,
                content={"error": "Approval not found or agent not configured"},
            )

        @app.post("/api/approvals/{approval_id}/deny")
        async def deny_tool(approval_id: str):
            """Deny a pending tool execution."""
            if self._agent and hasattr(self._agent, 'deny_tool'):
                result = self._agent.deny_tool(approval_id)
                return {"status": "denied", "approval_id": approval_id, "result": result}
            return JSONResponse(
                status_code=404,
                content={"error": "Approval not found or agent not configured"},
            )

        @app.get("/api/config/api-keys")
        async def get_api_keys_status():
            """Return which API keys are set (masked values)."""
            keys = {}
            for key_name in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"]:
                val = os.environ.get(key_name, "")
                if val:
                    keys[key_name] = {"set": True, "masked": val[:8] + "***" if len(val) > 8 else "***"}
                else:
                    keys[key_name] = {"set": False, "masked": ""}
            return {"keys": keys}

        async def _validate_api_key(key_name: str, value: str) -> dict:
            """Validate an API key by making a lightweight request to the provider."""
            import aiohttp
            try:
                if key_name == "ANTHROPIC_API_KEY":
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://api.anthropic.com/v1/models",
                            headers={"x-api-key": value, "anthropic-version": "2023-06-01"},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                return {"valid": True, "reason": ""}
                            elif resp.status == 401:
                                return {"valid": False, "reason": "Invalid API key (401 Unauthorized)"}
                            else:
                                return {"valid": False, "reason": f"Unexpected response: HTTP {resp.status}"}

                elif key_name == "GEMINI_API_KEY":
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"https://generativelanguage.googleapis.com/v1beta/models?key={value}",
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                return {"valid": True, "reason": ""}
                            elif resp.status == 400 or resp.status == 403:
                                return {"valid": False, "reason": "Invalid API key"}
                            else:
                                return {"valid": False, "reason": f"Unexpected response: HTTP {resp.status}"}

                elif key_name == "OPENAI_API_KEY":
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://api.openai.com/v1/models",
                            headers={"Authorization": f"Bearer {value}"},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                return {"valid": True, "reason": ""}
                            elif resp.status == 401:
                                return {"valid": False, "reason": "Invalid API key (401 Unauthorized)"}
                            else:
                                return {"valid": False, "reason": f"Unexpected response: HTTP {resp.status}"}

                return {"valid": True, "reason": ""}  # Unknown key type, skip validation
            except aiohttp.ClientError as e:
                return {"valid": False, "reason": f"Connection error: {e}"}
            except asyncio.TimeoutError:
                return {"valid": False, "reason": "Validation request timed out"}

        @app.post("/api/config/api-keys")
        async def update_api_key(request: Request):
            """Update an API key — encrypted in DB, or fallback to .env."""
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
            if self._db:
                try:
                    await save_api_key_to_db(self._db, key_name, value)
                    persisted_to = "db_encrypted"
                except Exception as e:
                    logger.warning(f"Failed to save API key to DB: {e}")
                    # Fallback: set in runtime only
                    os.environ[key_name] = value
            else:
                # No DB — save to .env as fallback
                from breadmind.config import save_env_var
                save_env_var(key_name, value)
                persisted_to = "env_file"

            masked = value[:8] + "***" if len(value) > 8 else "***"
            return {"status": "ok", "masked": masked, "storage": persisted_to}

        @app.post("/api/config/provider")
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
                if self._config:
                    self._config.llm.default_provider = provider

            if model is not None:
                if self._config:
                    self._config.llm.default_model = model

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
                if self._config:
                    self._config.llm.tool_call_max_turns = max_turns

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
                if self._config:
                    self._config.llm.tool_call_timeout_seconds = timeout

            # Persist to DB
            if self._db and self._config:
                try:
                    await self._db.set_setting("llm", {
                        "default_provider": self._config.llm.default_provider,
                        "default_model": self._config.llm.default_model,
                        "tool_call_max_turns": self._config.llm.tool_call_max_turns,
                        "tool_call_timeout_seconds": self._config.llm.tool_call_timeout_seconds,
                    })
                except Exception as e:
                    logger.warning(f"Failed to persist LLM settings to DB: {e}")

            return {"status": "ok", "persisted": self._db is not None}

        @app.get("/api/config/models/{provider}")
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

        @app.post("/api/config/mcp")
        async def update_mcp(request: Request):
            """Update MCP configuration."""
            data = await request.json()
            auto_discover = data.get("auto_discover")
            max_restart = data.get("max_restart_attempts")

            if self._config:
                if auto_discover is not None:
                    self._config.mcp.auto_discover = bool(auto_discover)
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
                    self._config.mcp.max_restart_attempts = max_restart

            # Persist to DB
            if self._db and self._config:
                try:
                    await self._db.set_setting("mcp", {
                        "auto_discover": self._config.mcp.auto_discover,
                        "max_restart_attempts": self._config.mcp.max_restart_attempts,
                    })
                except Exception as e:
                    logger.warning(f"Failed to persist MCP settings to DB: {e}")

            return {"status": "ok", "persisted": self._db is not None}

        @app.get("/api/config/persona")
        async def get_persona():
            """Get current persona settings."""
            from breadmind.config import DEFAULT_PERSONA, DEFAULT_PERSONA_PRESETS
            if self._config and hasattr(self._config, '_persona') and self._config._persona:
                persona = self._config._persona
            else:
                persona = DEFAULT_PERSONA
            return {"persona": persona, "presets": list(DEFAULT_PERSONA_PRESETS.keys())}

        @app.post("/api/config/persona")
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
            if self._config:
                self._config._persona = persona
            if self._agent and hasattr(self._agent, 'set_persona'):
                self._agent.set_persona(persona)

            # Persist to DB
            if self._db:
                try:
                    await self._db.set_setting("persona", persona)
                except Exception as e:
                    logger.warning(f"Failed to persist persona to DB: {e}")

            return {"status": "ok", "persona": persona}

        @app.get("/api/config/settings-status")
        async def get_settings_status():
            """Check if settings are DB-persisted."""
            return {"db_connected": self._db is not None}

        # --- MCP Store endpoints ---

        @app.get("/api/mcp/search")
        async def mcp_search(q: str = "", limit: int = 10, source: str = ""):
            if not self._mcp_store:
                return {"results": []}
            results = await self._mcp_store.search(q, limit=limit)
            if source:
                results = [r for r in results if r.get("source") == source]
            return {"results": results}

        @app.get("/api/mcp/featured")
        async def mcp_featured(source: str = ""):
            """Return featured/recommended MCP servers by category."""
            if not self._mcp_store:
                return {"categories": []}
            categories = [
                {"name": "Infrastructure", "icon": "🏗️", "query": "kubernetes docker"},
                {"name": "Development", "icon": "💻", "query": "github git code"},
                {"name": "Database", "icon": "🗄️", "query": "database sql postgres"},
                {"name": "AI & LLM", "icon": "🤖", "query": "ai llm openai"},
                {"name": "Monitoring", "icon": "📊", "query": "monitoring metrics"},
                {"name": "Cloud", "icon": "☁️", "query": "aws azure cloud"},
                {"name": "Network", "icon": "🌐", "query": "network http api"},
                {"name": "File & Storage", "icon": "📁", "query": "file storage s3"},
            ]
            import asyncio
            async def fetch_category(cat):
                results = await self._mcp_store.search(cat["query"], limit=4)
                if source:
                    results = [r for r in results if r.get("source") == source]
                return {**cat, "servers": results}
            tasks = [fetch_category(c) for c in categories]
            filled = await asyncio.gather(*tasks)
            # Only return categories that have results
            return {"categories": [c for c in filled if c.get("servers")]}

        @app.get("/api/mcp/server-detail")
        async def mcp_detail(source: str = "", slug: str = ""):
            """Get detailed info for an MCP server."""
            import aiohttp
            detail = {"slug": slug, "source": source, "name": slug, "description": "", "version": "",
                      "website": "", "repository": "", "install_command": "",
                      "trust": {"level": "community", "verified": False, "official": False, "owner": "", "has_repo": False, "updated_at": ""}}
            try:
                if source == "clawhub":
                    detail["website"] = f"https://clawhub.ai/skills/{slug}"
                    detail["install_command"] = f"clawhub install {slug}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://clawhub.ai/api/search",
                            params={"q": slug, "limit": 5},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                for r in data.get("results", []):
                                    if r.get("slug") == slug:
                                        detail["name"] = r.get("displayName", slug)
                                        detail["description"] = r.get("summary", "")
                                        detail["version"] = r.get("version") or ""
                                        # Trust info from ClawHub
                                        updated = r.get("updatedAt")
                                        if updated:
                                            from datetime import datetime, timezone
                                            try:
                                                dt = datetime.fromtimestamp(updated / 1000, tz=timezone.utc)
                                                detail["trust"]["updated_at"] = dt.strftime("%Y-%m-%d")
                                            except Exception:
                                                pass
                                        break
                        # Check owner via page URL pattern
                        detail["trust"]["owner"] = "clawhub"
                        # Official ClawHub skills are under @skills owner
                        if slug.startswith("openclaw") or slug in ("docker-essentials", "git-essentials", "kubernetes-devops"):
                            detail["trust"]["official"] = True
                            detail["trust"]["verified"] = True
                            detail["trust"]["level"] = "official"
                        else:
                            detail["trust"]["level"] = "community"

                elif source == "mcp_registry":
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"https://registry.modelcontextprotocol.io/v0.1/servers/{slug}/versions/latest",
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                srv = data.get("server", data)
                                detail["name"] = srv.get("title", srv.get("name", slug))
                                detail["description"] = srv.get("description", "")
                                detail["version"] = srv.get("version", "")
                                detail["website"] = srv.get("websiteUrl", "")
                                repo = srv.get("repository", {})
                                detail["repository"] = repo.get("url", "") if isinstance(repo, dict) else ""
                                detail["install_command"] = f"npx -y {slug}"
                                # Trust info from MCP Registry _meta
                                meta = data.get("_meta", {})
                                official_meta = meta.get("io.modelcontextprotocol.registry/official", {})
                                if official_meta.get("status") == "active":
                                    detail["trust"]["verified"] = True
                                    detail["trust"]["official"] = True
                                    detail["trust"]["level"] = "verified"
                                detail["trust"]["has_repo"] = bool(detail["repository"])
                                detail["trust"]["owner"] = repo.get("source", "") if isinstance(repo, dict) else ""
                                updated = official_meta.get("updatedAt", "")
                                if updated:
                                    detail["trust"]["updated_at"] = updated[:10]
            except Exception as e:
                logger.warning(f"Failed to fetch detail for {source}/{slug}: {e}")
            return {"detail": detail}

        @app.post("/api/mcp/install/analyze")
        async def mcp_install_analyze(request: Request):
            if not self._mcp_store:
                return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
            data = await request.json()
            analysis = await self._mcp_store.analyze_server(data)
            return {"analysis": analysis}

        @app.post("/api/mcp/install/execute")
        async def mcp_install_execute(request: Request):
            if not self._mcp_store:
                return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
            data = await request.json()
            result = await self._mcp_store.install_server(
                name=data.get("name", ""),
                slug=data.get("slug", ""),
                command=data.get("command", ""),
                args=data.get("args", []),
                env=data.get("env", {}),
                source=data.get("source", ""),
                runtime=data.get("runtime", ""),
            )
            # Broadcast install event to WebSocket clients
            if result.get("status") == "ok":
                await self.broadcast_event({"type": "mcp_installed", "server": result})
            return result

        @app.post("/api/mcp/install/troubleshoot")
        async def mcp_install_troubleshoot(request: Request):
            if not self._mcp_store:
                return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
            data = await request.json()
            if not self._mcp_store._assistant:
                return JSONResponse(status_code=503, content={"error": "LLM not available for troubleshooting"})
            fix = await self._mcp_store._assistant.troubleshoot(
                data.get("server_name", ""), data.get("command", ""),
                data.get("args", []), data.get("error_log", ""),
            )
            return {"fix": fix}

        @app.get("/api/mcp/installed")
        async def mcp_installed():
            if not self._mcp_store:
                return {"servers": []}
            servers = await self._mcp_store.list_installed()
            return {"servers": servers}

        @app.post("/api/mcp/servers/{name}/start")
        async def mcp_server_start(name: str):
            if not self._mcp_store:
                return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
            result = await self._mcp_store.start_server(name)
            return result

        @app.post("/api/mcp/servers/{name}/stop")
        async def mcp_server_stop(name: str):
            if not self._mcp_store:
                return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
            result = await self._mcp_store.stop_server(name)
            return result

        @app.delete("/api/mcp/servers/{name}")
        async def mcp_server_remove(name: str):
            if not self._mcp_store:
                return JSONResponse(status_code=503, content={"error": "MCP Store not configured"})
            result = await self._mcp_store.remove_server(name)
            return result

        @app.get("/api/mcp/servers/{name}/tools")
        async def mcp_server_tools(name: str):
            if not self._mcp_store:
                return {"tools": []}
            tools = await self._mcp_store.get_server_tools(name)
            return {"tools": tools}

        # --- Monitoring Rules ---
        @app.get("/api/config/monitoring/rules")
        async def get_monitoring_rules():
            if self._monitoring_engine and hasattr(self._monitoring_engine, 'get_rules_config'):
                rules = self._monitoring_engine.get_rules_config()
                lp = self._monitoring_engine.get_loop_protector_config()
                return {"rules": rules, "loop_protector": lp}
            return {"rules": [], "loop_protector": {}}

        @app.post("/api/config/monitoring/rules")
        async def update_monitoring_rules(request: Request):
            data = await request.json()
            if not self._monitoring_engine:
                return JSONResponse(status_code=503, content={"error": "Monitoring not configured"})
            # Update individual rules
            for rule_update in data.get("rules", []):
                name = rule_update.get("name")
                if "enabled" in rule_update:
                    if rule_update["enabled"]:
                        self._monitoring_engine.enable_rule(name)
                    else:
                        self._monitoring_engine.disable_rule(name)
                if "interval_seconds" in rule_update:
                    self._monitoring_engine.update_rule_interval(name, rule_update["interval_seconds"])
            # Update loop protector
            lp = data.get("loop_protector", {})
            if lp:
                self._monitoring_engine.update_loop_protector_config(
                    cooldown_minutes=lp.get("cooldown_minutes"),
                    max_auto_actions=lp.get("max_auto_actions"),
                )
            if self._db:
                try:
                    await self._db.set_setting("monitoring_config", data)
                except Exception:
                    pass
            return {"status": "ok"}

        # --- Messenger Allowed Users ---
        @app.get("/api/config/messenger")
        async def get_messenger_config():
            if self._message_router and hasattr(self._message_router, 'get_allowed_users'):
                return {"allowed_users": self._message_router.get_allowed_users()}
            return {"allowed_users": {"slack": [], "discord": [], "telegram": []}}

        @app.post("/api/config/messenger")
        async def update_messenger_config(request: Request):
            data = await request.json()
            if not self._message_router:
                return JSONResponse(status_code=503, content={"error": "Messenger not configured"})
            for platform, users in data.get("allowed_users", {}).items():
                self._message_router.update_allowed_users(platform, users)
            if self._db:
                try:
                    await self._db.set_setting("messenger_config", data.get("allowed_users", {}))
                except Exception:
                    pass
            return {"status": "ok"}

        # --- Messenger Connection Settings ---
        @app.get("/api/messenger/platforms")
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
            }
            token_keys = {
                "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
                "discord": ["DISCORD_BOT_TOKEN"],
                "telegram": ["TELEGRAM_BOT_TOKEN"],
            }
            for platform, cfg in configs.items():
                tokens_set = all(bool(os.environ.get(k, "")) for k in token_keys.get(platform, []))
                connected = False
                if self._message_router and hasattr(self._message_router, 'get_platform_status'):
                    status = self._message_router.get_platform_status()
                    connected = status.get(platform, {}).get("connected", False)
                allowed = []
                if self._message_router and hasattr(self._message_router, 'get_allowed_users'):
                    allowed = self._message_router.get_allowed_users().get(platform, [])

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
            valid_platforms = {"slack", "discord", "telegram"}
            if platform not in valid_platforms:
                return JSONResponse(status_code=400, content={"error": f"Invalid platform: {platform}"})

            token_map = {
                "slack": {"bot_token": "SLACK_BOT_TOKEN", "app_token": "SLACK_APP_TOKEN"},
                "discord": {"bot_token": "DISCORD_BOT_TOKEN"},
                "telegram": {"bot_token": "TELEGRAM_BOT_TOKEN"},
            }

            saved = {}
            for field_name, env_key in token_map.get(platform, {}).items():
                value = data.get(field_name, "")
                if value:
                    os.environ[env_key] = value
                    if self._db:
                        try:
                            await self._db.set_setting(f"messenger_token:{env_key}", {"value": value})
                        except Exception as e:
                            logger.warning(f"Failed to save messenger token to DB: {e}")
                    saved[field_name] = env_key

            return {"status": "ok", "saved": list(saved.keys()), "platform": platform}

        @app.post("/api/messenger/{platform}/test")
        async def test_messenger(platform: str):
            """Send a test message to verify connection."""
            valid_platforms = {"slack", "discord", "telegram"}
            if platform not in valid_platforms:
                return JSONResponse(status_code=400, content={"error": f"Invalid platform: {platform}"})
            if not self._message_router:
                return JSONResponse(status_code=503, content={"error": "Message router not configured"})
            gw = self._message_router._gateways.get(platform)
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
                        {"step": 2, "text": "Click 'Create New App' → 'From scratch'"},
                        {"step": 3, "text": "Add Bot Token Scopes: chat:write, app_mentions:read, channels:read, im:read, im:write"},
                        {"step": 4, "text": "Enable Socket Mode and get an App Token (xapp-...)"},
                        {"step": 5, "text": "Install app to your workspace"},
                        {"step": 6, "text": "Copy Bot Token (xoxb-...) and App Token here"},
                    ]}
                redirect_uri = f"http://localhost:{self._config.web.port if self._config else 8080}/api/messenger/slack/oauth-callback"
                scopes = "chat:write,app_mentions:read,channels:read,im:read,im:write,im:history"
                url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scopes}&redirect_uri={redirect_uri}"
                return {"url": url, "steps": []}

            elif platform == "discord":
                client_id = os.environ.get("DISCORD_CLIENT_ID", "")
                if not client_id:
                    return {"url": None, "steps": [
                        {"step": 1, "text": "Go to Discord Developer Portal", "link": "https://discord.com/developers/applications"},
                        {"step": 2, "text": "Click 'New Application' → name it 'BreadMind'"},
                        {"step": 3, "text": "Go to 'Bot' tab → click 'Add Bot'"},
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
                            if self._db:
                                try:
                                    from breadmind.config import encrypt_value
                                    await self._db.set_setting("messenger_token:SLACK_BOT_TOKEN", {"encrypted": encrypt_value(bot_token)})
                                except Exception:
                                    pass
                            # Notify WebSocket clients
                            await self.broadcast_event({"type": "messenger_connected", "platform": "slack"})
                            return HTMLResponse(
                                "<html><body style='background:#0d1117;color:#e2e8f0;font-family:sans-serif;text-align:center;padding:60px;'>"
                                "<h1>✅ Slack Connected!</h1><p>Bot token saved. You can close this window.</p>"
                                "<script>setTimeout(function(){window.close();},3000);</script>"
                                "<p style='color:#64748b;font-size:13px;'>This window will close in 3 seconds...</p>"
                                "<p><a href='/' style='color:#60a5fa;'>Back to BreadMind</a></p></body></html>"
                            )
                        else:
                            err = data.get("error", "unknown")
                            return HTMLResponse(f"<html><body><h1>Slack OAuth Failed</h1><p>{err}</p></body></html>")
            except Exception as e:
                return HTMLResponse(f"<html><body><h1>Error</h1><p>{e}</p></body></html>")

        # --- Memory Config ---
        @app.get("/api/config/memory")
        async def get_memory_config():
            if self._working_memory and hasattr(self._working_memory, 'get_config'):
                return {"memory": self._working_memory.get_config()}
            return {"memory": {"max_messages_per_session": 50, "session_timeout_minutes": 30, "active_sessions": 0}}

        @app.post("/api/config/memory")
        async def update_memory_config(request: Request):
            data = await request.json()
            if self._working_memory:
                self._working_memory.update_config(
                    max_messages=data.get("max_messages"),
                    timeout_minutes=data.get("timeout_minutes"),
                )
            if self._db:
                try:
                    await self._db.set_setting("memory_config", data)
                except Exception:
                    pass
            return {"status": "ok"}

        # --- Tool Security ---
        @app.get("/api/config/tool-security")
        async def get_tool_security():
            from breadmind.tools.builtin import ToolSecurityConfig
            return {"security": ToolSecurityConfig.get_config()}

        @app.post("/api/config/tool-security")
        async def update_tool_security(request: Request):
            from breadmind.tools.builtin import ToolSecurityConfig
            data = await request.json()
            ToolSecurityConfig.update(
                dangerous_patterns=data.get("dangerous_patterns"),
                sensitive_patterns=data.get("sensitive_patterns"),
                allowed_ssh_hosts=data.get("allowed_ssh_hosts"),
                base_directory=data.get("base_directory"),
            )
            if self._db:
                try:
                    await self._db.set_setting("tool_security", ToolSecurityConfig.get_config())
                except Exception:
                    pass
            return {"status": "ok"}

        # --- Agent Timeouts ---
        @app.get("/api/config/timeouts")
        async def get_timeouts():
            if self._agent and hasattr(self._agent, 'get_timeouts'):
                return {"timeouts": self._agent.get_timeouts()}
            return {"timeouts": {"tool_timeout": 30, "chat_timeout": 120, "max_turns": 10}}

        @app.post("/api/config/timeouts")
        async def update_timeouts(request: Request):
            data = await request.json()
            if self._agent:
                if hasattr(self._agent, 'update_timeouts'):
                    self._agent.update_timeouts(
                        tool_timeout=data.get("tool_timeout"),
                        chat_timeout=data.get("chat_timeout"),
                    )
                if "max_turns" in data and hasattr(self._agent, 'update_max_turns'):
                    self._agent.update_max_turns(data["max_turns"])
            if self._db:
                try:
                    await self._db.set_setting("agent_timeouts", data)
                except Exception:
                    pass
            return {"status": "ok"}

        # --- Logging Level ---
        @app.post("/api/config/logging")
        async def update_logging(request: Request):
            import logging as _logging
            data = await request.json()
            level = data.get("level", "INFO").upper()
            valid = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if level not in valid:
                return JSONResponse(status_code=400, content={"error": f"Invalid level. Must be one of {valid}"})
            _logging.getLogger().setLevel(getattr(_logging, level))
            if self._config:
                self._config.logging.level = level
            if self._db:
                try:
                    await self._db.set_setting("logging_config", {"level": level})
                except Exception:
                    pass
            return {"status": "ok", "level": level}

        @app.get("/api/update/check")
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

        @app.post("/api/update/apply")
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

        @app.post("/api/update/restart")
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

        @app.websocket("/ws/chat")
        async def websocket_chat(websocket: WebSocket):
            await websocket.accept()
            async with self._lock:
                self._connections.append(websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    user_message = msg.get("message", "")

                    if self._message_handler:
                        if asyncio.iscoroutinefunction(self._message_handler):
                            response = await self._message_handler(user_message, user="web", channel="web")
                        else:
                            response = self._message_handler(user_message, user="web", channel="web")
                    else:
                        response = "No message handler configured."

                    await websocket.send_text(json.dumps({"type": "response", "message": response}))
            except WebSocketDisconnect:
                async with self._lock:
                    if websocket in self._connections:
                        self._connections.remove(websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                async with self._lock:
                    if websocket in self._connections:
                        self._connections.remove(websocket)

    async def broadcast(self, message: str):
        async with self._lock:
            connections = self._connections[:]
        for ws in connections:
            try:
                await ws.send_text(json.dumps({"type": "notification", "message": message}))
            except Exception:
                async with self._lock:
                    if ws in self._connections:
                        self._connections.remove(ws)
