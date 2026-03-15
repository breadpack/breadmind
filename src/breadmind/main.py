import argparse
import asyncio
import logging
import os
import signal
import sys
from breadmind.config import load_config, load_safety_config, get_default_config_dir, set_env_file_path
from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.ollama import OllamaProvider
from breadmind.memory.working import WorkingMemory
from breadmind.monitoring.engine import MonitoringEngine
from breadmind.tools.registry import ToolRegistry
from breadmind.tools.builtin import shell_exec, web_search, file_read, file_write, messenger_connect
from breadmind.tools.mcp_client import MCPClientManager
from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig
from breadmind.tools.meta import create_meta_tools

# Optional imports - may not be available yet
try:
    from breadmind.core.audit import AuditLogger
except ImportError:
    AuditLogger = None

try:
    from breadmind.core.metrics import MetricsCollector
except ImportError:
    MetricsCollector = None

try:
    from breadmind.core.context import ContextBuilder
except ImportError:
    ContextBuilder = None


def create_provider(config):
    provider_name = config.llm.default_provider
    if provider_name == "claude":
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not set, falling back to ollama")
            return OllamaProvider()
        return ClaudeProvider(api_key=api_key, default_model=config.llm.default_model)
    elif provider_name == "gemini":
        import os
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("Warning: GEMINI_API_KEY not set, falling back to ollama")
            return OllamaProvider()
        from breadmind.llm.gemini import GeminiProvider
        return GeminiProvider(api_key=api_key, default_model=config.llm.default_model)
    elif provider_name == "grok":
        import os
        api_key = os.environ.get("XAI_API_KEY", "")
        if not api_key:
            print("Warning: XAI_API_KEY not set, falling back to ollama")
            return OllamaProvider()
        from breadmind.llm.grok import GrokProvider
        return GrokProvider(api_key=api_key, default_model=config.llm.default_model)
    elif provider_name == "cli":
        from breadmind.llm.cli import CLIProvider
        model = config.llm.default_model or "claude -p"
        # Parse command from model string (e.g. "claude -p" → command="claude", args=["-p"])
        parts = model.split()
        return CLIProvider(command=parts[0], args=parts[1:], name="cli")
    elif provider_name == "ollama":
        return OllamaProvider()
    else:
        return OllamaProvider()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BreadMind AI Infrastructure Agent")
    parser.add_argument("--web", action="store_true", help="Start web UI mode with uvicorn")
    parser.add_argument("--host", default=None, help="Web server host (default: from config or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Web server port (default: from config or 8080)")
    parser.add_argument("--config-dir", default=None,
                        help="Config directory path (default: platform-specific)")
    parser.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        help="Logging level (default: from config or INFO)")
    return parser.parse_args()


async def run():
    args = _parse_args()
    config_dir = args.config_dir or get_default_config_dir()

    # Try platform config dir first, fall back to local ./config
    if os.path.isdir(config_dir) and os.path.exists(os.path.join(config_dir, "config.yaml")):
        config = load_config(config_dir)
        safety_cfg = load_safety_config(config_dir)
        print(f"  Config: {config_dir}")
    elif os.path.isdir("config"):
        config = load_config("config")
        safety_cfg = load_safety_config("config")
        config_dir = "config"
        print(f"  Config: ./config (local)")
    else:
        config = load_config(config_dir)  # will return defaults
        safety_cfg = load_safety_config(config_dir)
        print(f"  Config: defaults (no config dir found)")

    config.validate()

    # Set .env file path based on resolved config dir
    set_env_file_path(os.path.join(config_dir, ".env"))

    # Configure logging
    log_level = args.log_level or config.logging.level
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Connect to database and load persisted settings
    db = None
    try:
        from breadmind.storage.database import Database
        db_cfg = config.database
        dsn = f"postgresql://{db_cfg.user}:{db_cfg.password}@{db_cfg.host}:{db_cfg.port}/{db_cfg.name}"
        db = Database(dsn)
        await db.connect()
        from breadmind.config import apply_db_settings
        await apply_db_settings(config, db)
        print("  Database connected, settings loaded")
    except Exception as e:
        print(f"  Database not available ({e}), using file-based config")
        db = None

    provider = create_provider(config)
    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    # Register built-in tools
    for t in [shell_exec, web_search, file_read, file_write, messenger_connect]:
        registry.register(t)

    # Initialize MCP
    mcp_manager = MCPClientManager(
        max_restart_attempts=config.mcp.max_restart_attempts,
        call_timeout=config.llm.tool_call_timeout_seconds,
    )

    # Set up MCP tool execution callback
    async def mcp_execute(server_name, tool_name, arguments):
        return await mcp_manager.call_tool(server_name, tool_name, arguments)
    registry._mcp_callback = mcp_execute

    # Connect configured MCP servers
    for name, srv_cfg in config.mcp.servers.items():
        try:
            transport = srv_cfg.get("transport", "stdio")
            if transport == "sse":
                defs = await mcp_manager.connect_sse_server(
                    name, srv_cfg["url"], headers=srv_cfg.get("headers"),
                )
            else:
                defs = await mcp_manager.start_stdio_server(
                    name, srv_cfg["command"], srv_cfg.get("args", []),
                    env=srv_cfg.get("env"),
                )
            for d in defs:
                registry.register_mcp_tool(d, server_name=name, execute_callback=mcp_execute)
            print(f"  Connected MCP server: {name} ({len(defs)} tools)")
        except Exception as e:
            print(f"  Failed to connect MCP server '{name}': {e}")

    # Register meta tools
    search_engine = RegistrySearchEngine([
        RegistryConfig(name=r.name, type=r.type, enabled=r.enabled, url=r.url)
        for r in config.mcp.registries
    ])
    meta_tools = create_meta_tools(mcp_manager, search_engine)
    for func in meta_tools.values():
        registry.register(func)

    # Initialize MCP Store
    mcp_store = None
    try:
        from breadmind.mcp.store import MCPStore
        from breadmind.mcp.install_assistant import InstallAssistant
        install_assistant = InstallAssistant(provider=provider)
        mcp_store = MCPStore(
            mcp_manager=mcp_manager,
            registry_search=search_engine,
            install_assistant=install_assistant,
            db=db,
            tool_registry=registry,
        )
        # Auto-restore previously running servers
        await mcp_store.auto_restore_servers()
        print(f"  MCP Store: ready")
    except Exception as e:
        print(f"  MCP Store: not available ({e})")

    # Initialize working memory
    working_memory = WorkingMemory()

    # Initialize monitoring engine
    monitoring_engine = MonitoringEngine()
    await monitoring_engine.start()

    # Set up graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler(sig, frame):
        shutdown_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: shutdown_event.set())
    else:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

    # Initialize optional components
    audit_logger = None
    if AuditLogger is not None:
        try:
            audit_logger = AuditLogger()
        except Exception:
            pass

    metrics_collector = None
    if MetricsCollector is not None:
        try:
            metrics_collector = MetricsCollector()
        except Exception:
            pass

    agent_kwargs = dict(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        max_turns=config.llm.tool_call_max_turns,
    )
    if audit_logger is not None:
        agent_kwargs["audit_logger"] = audit_logger

    agent = CoreAgent(**agent_kwargs)

    # Wire metrics_collector to registry if supported
    if metrics_collector is not None and hasattr(registry, 'set_metrics_collector'):
        registry.set_metrics_collector(metrics_collector)

    # Wire ContextBuilder if available
    context_builder = None
    if ContextBuilder is not None:
        try:
            context_builder = ContextBuilder(agent=agent)
        except Exception:
            pass

    builtin_count = len([t for t in registry.get_all_definitions() if registry.get_tool_source(t.name) == "builtin"])
    print("BreadMind v0.1.0 - AI Infrastructure Agent")
    print(f"  Built-in tools: {builtin_count}")
    print(f"  Meta tools: {len(meta_tools)}")
    print(f"  MCP servers: {len(config.mcp.servers)}")

    # Resolve host/port from CLI args or config
    web_host = args.host or config.web.host
    web_port = args.port or config.web.port

    # Background update checker
    async def check_updates_periodically():
        import aiohttp
        while True:
            await asyncio.sleep(3600)  # Check every hour
            try:
                current = "0.1.0"
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://pypi.org/pypi/breadmind/json",
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            latest = data.get("info", {}).get("version", current)
                            if latest != current:
                                print(f"  Update available: v{current} → v{latest}")
                                # If web app running, broadcast notification
                                if args.web and 'web_app' in dir():
                                    await web_app.broadcast_event({
                                        "type": "update_available",
                                        "current": current,
                                        "latest": latest,
                                    })
            except Exception:
                pass

    update_task = asyncio.create_task(check_updates_periodically())

    try:
        if args.web:
            import uvicorn
            from breadmind.web.app import WebApp

            web_app = WebApp(
                message_handler=agent.handle_message,
                tool_registry=registry,
                mcp_manager=mcp_manager,
                config=config,
                monitoring_engine=monitoring_engine,
                safety_config=safety_cfg,
                agent=agent,
                audit_logger=audit_logger,
                metrics_collector=metrics_collector,
                database=db,
                mcp_store=mcp_store,
                safety_guard=guard,
                working_memory=working_memory,
            )
            print(f"  Starting web server on {web_host}:{web_port}")
            server_config = uvicorn.Config(
                web_app.app, host=web_host, port=web_port, log_level=log_level.lower(),
            )
            server = uvicorn.Server(server_config)
            await server.serve()
        else:
            print("Type 'quit' to exit.\n")
            while not shutdown_event.is_set():
                try:
                    user_input = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: input("you> ").strip(),
                    )
                except (EOFError, KeyboardInterrupt):
                    break
                if not user_input or user_input.lower() in ("quit", "exit"):
                    break

                response = await agent.handle_message(user_input, user="local", channel="cli")
                print(f"breadmind> {response}\n")
    finally:
        update_task.cancel()
        await monitoring_engine.stop()
        await mcp_manager.stop_all()
        working_memory._sessions.clear()
        if db:
            await db.disconnect()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
