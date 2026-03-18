import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MCPStore:
    """MCP server search, install, and lifecycle management."""

    def __init__(self, mcp_manager, registry_search, install_assistant=None, db=None, tool_registry=None):
        self._mcp = mcp_manager  # MCPClientManager
        self._search = registry_search  # RegistrySearchEngine
        self._assistant = install_assistant  # InstallAssistant (optional)
        self._db = db  # Database (optional)
        self._tool_registry = tool_registry

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search MCP registries."""
        results = await self._search.search(query, limit=limit)
        return [
            {"name": r.name, "slug": r.slug, "description": r.description,
             "source": r.source, "install_command": r.install_command}
            for r in results
        ]

    async def analyze_server(self, server_meta: dict) -> dict:
        """Use LLM to analyze server and determine install requirements."""
        if self._assistant:
            return await self._assistant.analyze(server_meta)
        # Fallback without LLM
        cmd = server_meta.get("install_command", "")
        parts = cmd.split() if cmd else []
        return {
            "runtime": "unknown", "command": parts[0] if parts else "",
            "args": parts[1:], "required_env": [], "optional_env": [],
            "dependencies": [], "summary": server_meta.get("description", ""),
        }

    async def install_server(self, name: str, slug: str, command: str, args: list[str],
                             env: dict[str, str] = None, source: str = "", runtime: str = "node") -> dict:
        """Install and start an MCP server."""
        env = env or {}
        try:
            # Start the MCP server process
            definitions = await self._mcp.start_stdio_server(
                name=name, command=command, args=args, env=env or None, source=source,
            )
            tool_names = [d.name for d in definitions]

            # Register tools
            if self._tool_registry:
                async def mcp_execute(server_name, tool_name, arguments):
                    return await self._mcp.call_tool(server_name, tool_name, arguments)
                for d in definitions:
                    self._tool_registry.register_mcp_tool(d, server_name=name, execute_callback=mcp_execute)

            # Persist to DB
            install_config = {
                "command": command, "args": args, "env": env,
                "source": source, "runtime": runtime, "slug": slug,
            }
            if self._db:
                try:
                    await self._save_server_to_db(name, install_config, "running")
                except Exception as e:
                    logger.warning(f"Failed to persist server to DB: {e}")

            return {"status": "ok", "name": name, "tools": tool_names, "tool_count": len(tool_names)}

        except Exception as e:
            error_log = str(e)
            result = {"status": "error", "name": name, "error": error_log}

            # Try LLM troubleshooting
            if self._assistant:
                try:
                    fix = await self._assistant.troubleshoot(name, command, args, error_log)
                    result["troubleshoot"] = fix
                except Exception:
                    pass

            return result

    async def stop_server(self, name: str) -> dict:
        """Stop a running MCP server."""
        try:
            await self._mcp.stop_server(name)
            if self._db:
                await self._update_server_status(name, "stopped")
            # Unregister tools
            if self._tool_registry:
                self._tool_registry.unregister_mcp_tools(name)
            return {"status": "ok", "name": name}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def remove_server(self, name: str) -> dict:
        """Stop and remove a server completely."""
        try:
            await self._mcp.stop_server(name)
        except Exception:
            pass
        if self._tool_registry:
            self._tool_registry.unregister_mcp_tools(name)
        if self._db:
            try:
                await self._remove_server_from_db(name)
            except Exception as e:
                logger.warning(f"Failed to remove server from DB: {e}")
        return {"status": "ok", "name": name}

    async def start_server(self, name: str) -> dict:
        """Start a previously installed server from DB config."""
        if not self._db:
            return {"status": "error", "error": "No database connection"}
        config = await self._get_server_config(name)
        if not config:
            return {"status": "error", "error": f"Server '{name}' not found in DB"}
        return await self.install_server(
            name=name, slug=config.get("slug", ""),
            command=config["command"], args=config.get("args", []),
            env=config.get("env", {}), source=config.get("source", ""),
            runtime=config.get("runtime", ""),
        )

    async def get_server_tools(self, name: str) -> list[dict]:
        """Get tools for a specific server."""
        if self._tool_registry:
            all_defs = self._tool_registry.get_all_definitions()
            return [
                {"name": d.name, "description": d.description}
                for d in all_defs
                if self._tool_registry.get_tool_source(d.name) == f"mcp:{name}"
                or d.name.startswith(f"{name}__")
            ]
        return []

    async def list_installed(self) -> list[dict]:
        """List all installed/running servers."""
        servers = []
        if self._mcp:
            try:
                srv_list = await self._mcp.list_servers()
                for s in srv_list:
                    servers.append({
                        "name": s.name, "status": s.status,
                        "tools": s.tools, "source": s.source,
                        "transport": s.transport,
                    })
            except Exception:
                pass
        # Also include stopped servers from DB
        if self._db:
            try:
                db_servers = await self._get_all_servers_from_db()
                running_names = {s["name"] for s in servers}
                for db_srv in db_servers:
                    if db_srv["name"] not in running_names:
                        servers.append({
                            "name": db_srv["name"], "status": db_srv["status"],
                            "tools": [], "source": db_srv.get("config", {}).get("source", ""),
                            "transport": "stdio",
                        })
            except Exception:
                pass
        return servers

    async def auto_restore_servers(self):
        """Restore previously running servers on startup."""
        if not self._db:
            return
        try:
            db_servers = await self._get_all_servers_from_db()
            for srv in db_servers:
                if srv["status"] == "running":
                    logger.info(f"Auto-restoring MCP server: {srv['name']}")
                    await self.start_server(srv["name"])
        except Exception as e:
            logger.warning(f"Failed to auto-restore servers: {e}")

    # --- DB helpers ---

    async def _save_server_to_db(self, name: str, config: dict, status: str):
        from breadmind.config import encrypt_value
        # Encrypt env vars
        if config.get("env"):
            encrypted_env = {}
            for k, v in config["env"].items():
                encrypted_env[k] = encrypt_value(v)
            config = {**config, "env_encrypted": encrypted_env}
            del config["env"]
        await self._db.set_setting(f"mcp_server:{name}", {
            "config": config, "status": status,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        })

    async def _update_server_status(self, name: str, status: str):
        data = await self._db.get_setting(f"mcp_server:{name}")
        if data:
            data["status"] = status
            await self._db.set_setting(f"mcp_server:{name}", data)

    async def _get_server_config(self, name: str) -> dict | None:
        data = await self._db.get_setting(f"mcp_server:{name}")
        if not data:
            return None
        config = data.get("config", {})
        # Decrypt env vars
        if "env_encrypted" in config:
            from breadmind.config import decrypt_value
            decrypted_env = {}
            for k, v in config["env_encrypted"].items():
                try:
                    decrypted_env[k] = decrypt_value(v)
                except Exception:
                    pass
            config["env"] = decrypted_env
            del config["env_encrypted"]
        return config

    async def _get_all_servers_from_db(self) -> list[dict]:
        all_settings = await self._db.get_all_settings()
        servers = []
        for key, value in all_settings.items():
            if key.startswith("mcp_server:"):
                name = key[len("mcp_server:"):]
                servers.append({"name": name, **value})
        return servers

    async def _remove_server_from_db(self, name: str):
        await self._db.delete_setting(f"mcp_server:{name}")
