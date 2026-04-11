"""Companion runtime: main event loop connecting to Commander."""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from typing import Any

from breadmind.companion.config import CompanionConfig
from breadmind.companion.security import PermissionManager
from breadmind.network.protocol import (
    MessageEnvelope,
    MessageType,
    SequenceTracker,
    create_message,
    deserialize_message,
    serialize_message,
)

logger = logging.getLogger(__name__)


class CompanionState:
    STARTING = "starting"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STOPPED = "stopped"


class CompanionRuntime:
    """Main event loop for the Companion Agent.

    Connects to Commander via WebSocket, sends heartbeats with device
    metrics, and dispatches incoming tasks to companion tools.
    """

    def __init__(
        self,
        config: CompanionConfig,
        platform_adapter: Any,
    ) -> None:
        self.config = config
        self._platform = platform_adapter
        self._permissions = PermissionManager(config.capabilities)
        self._ws: Any | None = None
        self._seq = SequenceTracker()
        self._session_key = (config.session_key or "companion-default-key").encode()
        self.state = CompanionState.STARTING
        self._stop_event = asyncio.Event()
        self._task_history: dict[str, dict] = {}
        self._tools: dict[str, Any] = {}

    def register_tools(self, tools: dict[str, Any]) -> None:
        """Register companion tool functions (name -> async callable)."""
        self._tools = tools

    async def start(self) -> None:
        """Connect to Commander, run heartbeat + message loops."""
        self.state = CompanionState.CONNECTING
        backoff = 1.0
        max_backoff = self.config.reconnect_max_backoff

        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
                backoff = 1.0  # reset on clean disconnect
            except Exception as e:
                logger.warning("Connection lost: %s (reconnecting in %.0fs)", e, backoff)
                self.state = CompanionState.DISCONNECTED
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

        self.state = CompanionState.STOPPED

    async def stop(self) -> None:
        """Request graceful shutdown."""
        self._stop_event.set()
        if self._ws is not None:
            await self._ws.close()
        self.state = CompanionState.STOPPED

    async def _connect_and_run(self) -> None:
        """Single connection lifecycle."""
        import websockets

        url = self.config.commander_url
        logger.info("Connecting to Commander at %s", url)

        async with websockets.connect(url) as ws:
            self._ws = ws
            self.state = CompanionState.CONNECTED
            logger.info("Connected to Commander")

            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            try:
                async for raw in ws:
                    if self._stop_event.is_set():
                        break
                    try:
                        msg = deserialize_message(raw, self._session_key)
                        await self._handle_message(msg)
                    except Exception as e:
                        logger.error("Failed to process message: %s", e)
            finally:
                heartbeat_task.cancel()
                self._ws = None

    async def _heartbeat_loop(self) -> None:
        """Periodically send heartbeat with device metrics."""
        while not self._stop_event.is_set():
            try:
                await self._send_heartbeat()
            except Exception as e:
                logger.debug("Heartbeat send failed: %s", e)
            await asyncio.sleep(self.config.heartbeat_interval)

    async def _send_heartbeat(self) -> None:
        """Build and send a heartbeat message."""
        env = await self._build_environment()
        metrics = await self._build_metrics()
        payload = {
            "host": self.config.device_name,
            "environment": env,
            **metrics,
        }
        msg = create_message(
            type=MessageType.HEARTBEAT,
            source=self.config.agent_id,
            target="commander",
            payload=payload,
        )
        await self._send(msg)

    async def _build_environment(self) -> dict[str, Any]:
        """Return device metadata for registration."""
        info = await self._platform.get_system_info()
        return {
            "agent_type": "companion",
            "device_name": self.config.device_name,
            "os": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "capabilities": list(self.config.capabilities.keys()),
            **info,
        }

    async def _build_metrics(self) -> dict[str, float]:
        """Collect current device metrics."""
        result: dict[str, float] = {}
        try:
            cpu = await self._platform.get_cpu_info()
            result["cpu"] = cpu.get("percent", 0) / 100
        except Exception:
            pass
        try:
            mem = await self._platform.get_memory_info()
            result["memory"] = mem.get("percent", 0) / 100
        except Exception:
            pass
        try:
            battery = await self._platform.get_battery_info()
            if battery:
                result["battery"] = battery.get("percent", 0) / 100
        except Exception:
            pass
        return result

    async def _handle_message(self, msg: MessageEnvelope) -> None:
        """Route incoming Commander message."""
        if msg.type == MessageType.TASK_ASSIGN:
            await self._handle_task(msg)
        elif msg.type == MessageType.COMMAND:
            await self._handle_command(msg)
        elif msg.type == MessageType.ROLE_UPDATE:
            logger.info("Role update received: %s", msg.payload)
        else:
            logger.warning("Unhandled message type: %s", msg.type)

    async def _handle_task(self, msg: MessageEnvelope) -> None:
        """Dispatch task to the appropriate companion tool."""
        payload = msg.payload
        task_id = payload.get("task_id", "")
        tool_name = payload.get("params", {}).get("tool", "")
        arguments = payload.get("params", {}).get("arguments", {})

        start = time.monotonic()
        if tool_name not in self._tools:
            result = {
                "task_id": task_id,
                "status": "failure",
                "output": f"Unknown companion tool: {tool_name}",
                "metrics": {},
            }
        elif not self._permissions.is_allowed(tool_name):
            result = {
                "task_id": task_id,
                "status": "failure",
                "output": f"Permission denied for tool: {tool_name}",
                "metrics": {},
            }
        else:
            try:
                output = await self._tools[tool_name](self._platform, self._permissions, arguments)
                result = {
                    "task_id": task_id,
                    "status": "success",
                    "output": output,
                    "metrics": {"duration_ms": int((time.monotonic() - start) * 1000)},
                }
            except Exception as e:
                result = {
                    "task_id": task_id,
                    "status": "failure",
                    "output": str(e),
                    "metrics": {"duration_ms": int((time.monotonic() - start) * 1000)},
                }

        self._task_history[task_id] = result
        reply = create_message(
            type=MessageType.TASK_RESULT,
            source=self.config.agent_id,
            target="commander",
            payload=result,
            reply_to=msg.id,
            trace_id=msg.trace_id,
        )
        await self._send(reply)

    async def _handle_command(self, msg: MessageEnvelope) -> None:
        action = msg.payload.get("action")
        if action == "restart":
            logger.info("Restart requested by Commander")
        elif action == "decommission":
            logger.info("Decommission requested, shutting down")
            await self.stop()
        else:
            logger.warning("Unknown command action: %s", action)

    async def _send(self, msg: MessageEnvelope) -> None:
        if self._ws is not None:
            raw = serialize_message(msg, self._session_key)
            await self._ws.send(raw)
