import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("breadmind.daemon")


@dataclass
class DaemonState:
    pid: int
    started_at: str
    host: str
    port: int
    status: str = "running"  # running, stopping, stopped


def get_pid_file() -> Path:
    """PID file path."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "breadmind"
    else:
        base = Path.home() / ".breadmind"
    base.mkdir(parents=True, exist_ok=True)
    return base / "daemon.pid"


def get_state_file() -> Path:
    """State file path."""
    return get_pid_file().with_suffix(".json")


def is_daemon_running() -> DaemonState | None:
    """Check if a daemon is currently running."""
    state_file = get_state_file()
    if not state_file.exists():
        return None
    try:
        state = DaemonState(**json.loads(state_file.read_text()))
        # Check if the PID is actually alive
        if _is_process_alive(state.pid):
            return state
        # PID file exists but process is dead — clean up
        state_file.unlink(missing_ok=True)
        get_pid_file().unlink(missing_ok=True)
        return None
    except Exception:
        return None


def _is_process_alive(pid: int) -> bool:
    """Check if a PID is alive."""
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, pid)  # PROCESS_QUERY_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


async def run_daemon(args) -> None:
    """Run BreadMind in daemon mode (foreground)."""
    # Check if already running
    existing = is_daemon_running()
    if existing:
        print(f"Daemon already running (PID {existing.pid})")
        return

    host = getattr(args, "host", "0.0.0.0") or "0.0.0.0"
    port = getattr(args, "port", 8080) or 8080

    # Write PID file
    pid = os.getpid()
    state = DaemonState(
        pid=pid,
        started_at=datetime.now(timezone.utc).isoformat(),
        host=host,
        port=port,
    )
    get_pid_file().write_text(str(pid))
    get_state_file().write_text(json.dumps(state.__dict__))

    print(f"BreadMind Daemon starting (PID {pid})")
    print(f"  API: http://{host}:{port}")

    shutdown_event = asyncio.Event()

    def _signal_handler(*_):
        shutdown_event.set()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: shutdown_event.set())
    else:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

    # Lightweight bootstrap
    services = await _bootstrap_daemon(args)

    if services is None:
        print("  Failed to start daemon. Run 'breadmind doctor' for diagnostics.")
        _cleanup_pid_files()
        return

    print(f"  Messengers: {services.get('messenger_count', 0)} connected")
    print(f"  MCP servers: {services.get('mcp_count', 0)} running")
    print(f"  Tools: {services.get('tool_count', 0)} registered")
    print("  Daemon ready. Press Ctrl+C to stop.")

    try:
        import uvicorn

        config = uvicorn.Config(
            services["app"],
            host=host,
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)

        # Wait for either server completion or shutdown signal
        server_task = asyncio.create_task(server.serve())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, pending = await asyncio.wait(
            [server_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
    finally:
        print("\n  Shutting down daemon...")
        await _shutdown_daemon(services)
        _cleanup_pid_files()
        print("  Daemon stopped.")


async def _bootstrap_daemon(args) -> dict | None:
    """Lightweight bootstrap for daemon mode."""
    try:
        from breadmind.config import (
            load_config,
            get_default_config_dir,
            load_safety_config,
            load_env_file,
            set_env_file_path,
        )

        config_dir = getattr(args, "config_dir", None) or get_default_config_dir()

        # Fall back to local ./config if platform config dir has no config.yaml
        if not os.path.exists(os.path.join(config_dir, "config.yaml")):
            if os.path.exists("config/config.yaml"):
                config_dir = "config"
            else:
                print("  Config not found. Run 'breadmind setup' first.")
                return None

        config = load_config(config_dir)
        safety_cfg = load_safety_config(config_dir)
        env_file = os.path.join(config_dir, ".env")
        set_env_file_path(env_file)
        load_env_file(env_file)
        config.validate()

        # Core services
        from breadmind.llm.factory import create_provider
        from breadmind.core.bootstrap import init_database, init_tools, init_memory, init_agent, init_messenger
        from breadmind.core.events import get_event_bus

        db = await init_database(config, config_dir)
        provider = create_provider(config)
        registry, guard, mcp_manager, search_engine, meta_tools = await init_tools(config, safety_cfg)

        # Memory
        memory_components = await init_memory(db, provider, config, registry, mcp_manager, search_engine)
        agent, _, audit_logger, metrics_collector = await init_agent(
            config, provider, registry, guard, db, memory_components,
        )

        # Messenger
        from breadmind.messenger.router import MessageRouter

        message_router = MessageRouter()
        messenger_components = None
        messenger_count = 0
        try:
            messenger_components = await init_messenger(db, message_router)
            messenger_count = len(messenger_components.get("gateways", []))
        except Exception as e:
            logger.warning("Messenger init: %s", e)

        # MCP count
        mcp_count = len(getattr(getattr(config, "mcp", None), "servers", {}))

        # Web app
        from breadmind.web.app import WebApp
        from breadmind.network.token_manager import TokenManager

        token_manager = TokenManager(db=db)
        await token_manager.load_from_db()

        web_app = WebApp(
            message_handler=agent.handle_message,
            tool_registry=registry,
            mcp_manager=mcp_manager,
            config=config,
            safety_config=safety_cfg,
            agent=agent,
            audit_logger=audit_logger,
            metrics_collector=metrics_collector,
            database=db,
            safety_guard=guard,
            working_memory=memory_components["working_memory"],
            search_engine=search_engine,
            token_manager=token_manager,
            message_router=message_router,
            messenger_security=messenger_components["security"] if messenger_components else None,
            lifecycle_manager=messenger_components["lifecycle"] if messenger_components else None,
            orchestrator=messenger_components["orchestrator"] if messenger_components else None,
        )

        # EventBus -> WebSocket broadcast
        event_bus = get_event_bus()

        async def _fwd(event):
            await web_app.broadcast_event({
                "type": event.type.value,
                "data": event.data,
            })

        event_bus.subscribe_all(_fwd)

        return {
            "app": web_app.app,
            "db": db,
            "mcp_manager": mcp_manager,
            "messenger_components": messenger_components,
            "memory_components": memory_components,
            "messenger_count": messenger_count,
            "mcp_count": mcp_count,
            "tool_count": len(registry.get_all_definitions()),
        }
    except Exception as e:
        logger.error("Bootstrap failed: %s", e)
        import traceback

        traceback.print_exc()
        return None


async def _shutdown_daemon(services: dict) -> None:
    """Clean up daemon services."""
    try:
        mc = services.get("messenger_components")
        if mc and mc.get("lifecycle"):
            await mc["lifecycle"].shutdown()
    except Exception as e:
        logger.warning("Messenger shutdown: %s", e)

    try:
        await services["mcp_manager"].stop_all()
    except Exception:
        pass

    try:
        if services.get("db"):
            await services["db"].disconnect()
    except Exception:
        pass


def _cleanup_pid_files():
    get_pid_file().unlink(missing_ok=True)
    get_state_file().unlink(missing_ok=True)


async def stop_daemon(args) -> None:
    """Stop the running daemon."""
    state = is_daemon_running()
    if not state:
        print("No daemon running.")
        return
    print(f"Stopping daemon (PID {state.pid})...")
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0001, False, state.pid)  # PROCESS_TERMINATE
            if handle:
                kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
        else:
            os.kill(state.pid, signal.SIGTERM)
        print("Daemon stopped.")
    except Exception as e:
        print(f"Failed to stop: {e}")
    _cleanup_pid_files()


async def daemon_status(args) -> None:
    """Show daemon status."""
    state = is_daemon_running()
    if not state:
        print("Daemon: not running")
    else:
        print(f"Daemon: running (PID {state.pid})")
        print(f"  Started: {state.started_at}")
        print(f"  API: http://{state.host}:{state.port}")
