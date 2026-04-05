from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class MCPToolDefinition:
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


@dataclass
class MCPServerConfig:
    name: str = "breadmind"
    version: str = "1.0.0"
    tools: list[MCPToolDefinition] = field(default_factory=list)


# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class MCPServer:
    """Expose BreadMind tools as an MCP server.

    Implements JSON-RPC 2.0 over stdio for the Model Context Protocol.
    Other MCP clients (Claude Desktop, Cursor, etc.) can invoke tools.

    Supports:
    - initialize / initialized handshake
    - tools/list — list available tools
    - tools/call — execute a tool
    """

    def __init__(self, config: MCPServerConfig | None = None):
        self._config = config or MCPServerConfig()
        self._initialized = False
        self._tool_handlers: dict[str, Callable] = {}
        self._tool_definitions: dict[str, MCPToolDefinition] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable,
    ) -> None:
        """Register a tool that can be invoked by MCP clients."""
        self._tool_handlers[name] = handler
        self._tool_definitions[name] = MCPToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
        )

    async def handle_message(self, message: dict) -> dict | None:
        """Handle a single JSON-RPC message. Returns response dict or None for notifications."""
        if "jsonrpc" not in message or message.get("jsonrpc") != "2.0":
            return self._error_response(
                message.get("id"), INVALID_REQUEST, "Invalid JSON-RPC version"
            )

        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")

        # Notifications (no id) — we still process but return None
        is_notification = msg_id is None

        if method == "initialize":
            if is_notification:
                return None
            return await self._handle_initialize(params, msg_id)
        elif method == "notifications/initialized":
            # Client acknowledgement — no response needed
            return None
        elif method == "tools/list":
            if not self._initialized:
                return self._error_response(msg_id, INVALID_REQUEST, "Not initialized")
            if is_notification:
                return None
            return await self._handle_tools_list(msg_id)
        elif method == "tools/call":
            if not self._initialized:
                return self._error_response(msg_id, INVALID_REQUEST, "Not initialized")
            if is_notification:
                return None
            return await self._handle_tools_call(params, msg_id)
        else:
            if is_notification:
                return None
            return self._error_response(msg_id, METHOD_NOT_FOUND, f"Unknown method: {method}")

    async def _handle_initialize(self, params: dict, id: int | str) -> dict:
        self._initialized = True
        return self._success_response(id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": self._config.name,
                "version": self._config.version,
            },
        })

    async def _handle_tools_list(self, id: int | str) -> dict:
        tools = []
        for defn in self._tool_definitions.values():
            tools.append({
                "name": defn.name,
                "description": defn.description,
                "inputSchema": defn.input_schema,
            })
        return self._success_response(id, {"tools": tools})

    async def _handle_tools_call(self, params: dict, id: int | str) -> dict:
        tool_name = params.get("name")
        if not tool_name:
            return self._error_response(id, INVALID_PARAMS, "Missing tool name")

        handler = self._tool_handlers.get(tool_name)
        if handler is None:
            return self._error_response(
                id, METHOD_NOT_FOUND, f"Unknown tool: {tool_name}"
            )

        arguments = params.get("arguments", {})
        try:
            import asyncio

            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)

            # Normalize result to MCP content format
            if isinstance(result, dict):
                text = json.dumps(result)
            elif isinstance(result, str):
                text = result
            else:
                text = str(result)

            return self._success_response(id, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })
        except Exception as exc:
            return self._success_response(id, {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            })

    def _error_response(self, id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": id,
            "error": {"code": code, "message": message},
        }

    def _success_response(self, id: Any, result: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": id,
            "result": result,
        }

    async def run_stdio(self) -> None:
        """Run the server reading JSON-RPC from stdin, writing to stdout.

        Each message is one JSON object per line.
        """
        import asyncio

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        loop = asyncio.get_running_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

        transport, _ = await loop.connect_write_pipe(
            asyncio.BaseProtocol, sys.stdout.buffer
        )

        while True:
            line = await reader.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                resp = self._error_response(None, PARSE_ERROR, "Parse error")
                transport.write((json.dumps(resp) + "\n").encode())
                continue

            response = await self.handle_message(message)
            if response is not None:
                transport.write((json.dumps(response) + "\n").encode())

    @property
    def tool_count(self) -> int:
        return len(self._tool_handlers)

    @property
    def initialized(self) -> bool:
        return self._initialized
