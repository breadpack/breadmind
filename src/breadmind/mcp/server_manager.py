"""MCP Server lifecycle manager with EventBus-driven hot-reload."""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any

from breadmind.core.events import EventBus, EventType
from breadmind.tools.mcp_protocol import (
    MCPError,
    create_initialize_request,
    create_initialized_notification,
    create_tools_call_request,
    create_tools_list_request,
    encode_message,
    parse_response,
)

logger = logging.getLogger(__name__)

_STARTUP_TIMEOUT = 30  # seconds for initialize + tools/list
_SHUTDOWN_TIMEOUT = 5  # seconds for graceful termination


@dataclass
class MCPServerConfig:
    name: str
    command: str  # e.g., "npx -y @modelcontextprotocol/server-github"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class MCPServerState:
    config: MCPServerConfig
    process: asyncio.subprocess.Process | None = None
    tools: list[dict] = field(default_factory=list)
    status: str = "stopped"  # stopped | starting | running | error
    error: str | None = None


class MCPServerManager:
    """MCP server lifecycle management with EventBus integration."""

    def __init__(self, event_bus: EventBus) -> None:
        self._servers: dict[str, MCPServerState] = {}
        self._event_bus = event_bus
        self._event_bus.on("mcp_server_add", self._on_server_add)
        self._event_bus.on("mcp_server_remove", self._on_server_remove)
        self._event_bus.on("mcp_server_restart", self._on_server_restart)

    # ── Public API ────────────────────────────────────────────────────

    async def add_server(self, config: MCPServerConfig) -> None:
        """Add a server, start it, and load its tool list."""
        if config.name in self._servers:
            await self.remove_server(config.name)

        state = MCPServerState(config=config)
        self._servers[config.name] = state

        await self._start_server(state)

        if state.status == "running":
            await self._event_bus.async_emit(
                EventType.MCP_SERVER_ADDED.value,
                {"name": config.name, "tools": state.tools},
            )
            await self._event_bus.async_emit(
                EventType.MCP_TOOLS_UPDATED.value,
                {"tools": await self.get_all_tools()},
            )

    async def remove_server(self, name: str) -> None:
        """Stop and remove a server."""
        state = self._servers.pop(name, None)
        if state is None:
            return
        await self._stop_server(state)
        await self._event_bus.async_emit(
            EventType.MCP_SERVER_REMOVED.value,
            {"name": name},
        )
        await self._event_bus.async_emit(
            EventType.MCP_TOOLS_UPDATED.value,
            {"tools": await self.get_all_tools()},
        )

    async def restart_server(self, name: str) -> None:
        """Restart a server (stop then start)."""
        state = self._servers.get(name)
        if state is None:
            return
        await self._stop_server(state)
        await self._start_server(state)
        if state.status == "running":
            await self._event_bus.async_emit(
                EventType.MCP_TOOLS_UPDATED.value,
                {"tools": await self.get_all_tools()},
            )

    async def get_server_status(self, name: str) -> MCPServerState | None:
        return self._servers.get(name)

    async def list_servers(self) -> list[MCPServerState]:
        return list(self._servers.values())

    async def get_all_tools(self) -> list[dict]:
        """Aggregate tools from all running servers."""
        tools: list[dict] = []
        for state in self._servers.values():
            if state.status == "running":
                tools.extend(state.tools)
        return tools

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> Any:
        """Call a tool on a specific running server."""
        state = self._servers.get(server_name)
        if state is None:
            raise ValueError(f"Server '{server_name}' not found")
        if state.status != "running" or state.process is None:
            raise RuntimeError(f"Server '{server_name}' is not running")

        request = create_tools_call_request(tool_name, arguments)
        await self._send_message(state.process, request)
        response = await self._read_message(state.process)
        return parse_response(response)

    async def shutdown_all(self) -> None:
        """Gracefully shut down every managed server."""
        names = list(self._servers.keys())
        for name in names:
            state = self._servers.pop(name, None)
            if state:
                await self._stop_server(state)

    # ── Internal: start / stop ────────────────────────────────────────

    async def _start_server(self, state: MCPServerState) -> None:
        cfg = state.config
        state.status = "starting"
        state.error = None
        state.tools = []

        cmd_parts = [cfg.command, *cfg.args]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=cfg.env or None,
            )
            state.process = process

            # Initialize handshake
            init_req = create_initialize_request()
            await self._send_message(process, init_req)
            init_resp = await asyncio.wait_for(
                self._read_message(process), timeout=_STARTUP_TIMEOUT
            )
            parse_response(init_resp)  # validate; raises MCPError on failure

            # Send initialized notification
            notif = create_initialized_notification()
            await self._send_message(process, notif)

            # Fetch tool list
            tools_req = create_tools_list_request()
            await self._send_message(process, tools_req)
            tools_resp = await asyncio.wait_for(
                self._read_message(process), timeout=_STARTUP_TIMEOUT
            )
            result = parse_response(tools_resp)
            state.tools = result.get("tools", []) if isinstance(result, dict) else []
            state.status = "running"

        except Exception as exc:
            state.status = "error"
            state.error = str(exc)
            # Kill the process if it was started
            if state.process is not None:
                try:
                    state.process.kill()
                    await state.process.wait()
                except ProcessLookupError:
                    pass
                state.process = None

            await self._event_bus.async_emit(
                EventType.MCP_SERVER_ERROR.value,
                {"name": cfg.name, "error": state.error},
            )

    async def _stop_server(self, state: MCPServerState) -> None:
        proc = state.process
        if proc is None:
            state.status = "stopped"
            return

        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=_SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass

        state.process = None
        state.status = "stopped"

    # ── Internal: JSON-RPC over stdio ─────────────────────────────────

    @staticmethod
    async def _send_message(
        process: asyncio.subprocess.Process, msg: dict
    ) -> None:
        assert process.stdin is not None
        data = encode_message(msg)
        process.stdin.write(data)
        await process.stdin.drain()

    @staticmethod
    async def _read_message(process: asyncio.subprocess.Process) -> dict:
        """Read a single Content-Length-framed JSON-RPC message from stdout."""
        assert process.stdout is not None
        # Read headers until empty line
        content_length: int | None = None
        while True:
            line = await process.stdout.readline()
            if not line:
                raise ConnectionError("MCP server process closed stdout")
            decoded = line.decode("utf-8").strip()
            if decoded == "":
                break
            if decoded.lower().startswith("content-length:"):
                content_length = int(decoded.split(":", 1)[1].strip())

        if content_length is None:
            raise ValueError("Missing Content-Length header in MCP response")

        body = await process.stdout.readexactly(content_length)
        return json.loads(body.decode("utf-8"))

    # ── Event handlers ────────────────────────────────────────────────

    async def _on_server_add(self, data: Any) -> None:
        if isinstance(data, MCPServerConfig):
            await self.add_server(data)
        elif isinstance(data, dict):
            config = MCPServerConfig(
                name=data["name"],
                command=data["command"],
                args=data.get("args", []),
                env=data.get("env", {}),
                enabled=data.get("enabled", True),
            )
            await self.add_server(config)

    async def _on_server_remove(self, data: Any) -> None:
        name = data if isinstance(data, str) else data.get("name", "")
        if name:
            await self.remove_server(name)

    async def _on_server_restart(self, data: Any) -> None:
        name = data if isinstance(data, str) else data.get("name", "")
        if name:
            await self.restart_server(name)
