import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from breadmind.llm.base import ToolDefinition
from breadmind.tools.registry import ToolResult
from breadmind.tools.mcp_protocol import (
    create_initialize_request, create_initialized_notification,
    create_tools_list_request, create_tools_call_request,
    encode_message, parse_response, MCPError,
)


@dataclass
class MCPServerInfo:
    name: str
    transport: str
    status: str
    tools: list[str] = field(default_factory=list)
    source: str = "config"


class MCPClientManager:
    def __init__(self, max_restart_attempts: int = 3):
        self._servers: dict[str, MCPServerInfo] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._sse_sessions: dict[str, dict] = {}
        self._max_restarts = max_restart_attempts
        self._restart_counts: dict[str, int] = {}

    def list_servers_sync(self) -> list[MCPServerInfo]:
        return list(self._servers.values())

    async def list_servers(self) -> list[MCPServerInfo]:
        return self.list_servers_sync()

    async def start_stdio_server(
        self, name: str, command: str, args: list[str],
        env: dict[str, str] | None = None, source: str = "config",
    ) -> list[ToolDefinition]:
        proc = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._processes[name] = proc

        init_req = create_initialize_request()
        await self._send_stdio(proc, init_req)
        init_resp = await self._read_stdio(proc)
        parse_response(init_resp)

        notif = create_initialized_notification()
        await self._send_stdio(proc, notif)

        tools_req = create_tools_list_request()
        await self._send_stdio(proc, tools_req)
        tools_resp = await self._read_stdio(proc)
        tools_result = parse_response(tools_resp)

        tool_names = []
        definitions = []
        for t in tools_result.get("tools", []):
            namespaced = f"{name}__{t['name']}"
            tool_names.append(t["name"])
            definitions.append(ToolDefinition(
                name=namespaced,
                description=t.get("description", ""),
                parameters=t.get("inputSchema", {"type": "object", "properties": {}}),
            ))

        self._servers[name] = MCPServerInfo(
            name=name, transport="stdio", status="running",
            tools=tool_names, source=source,
        )
        self._restart_counts[name] = 0
        return definitions

    async def connect_sse_server(
        self, name: str, url: str,
        headers: dict[str, str] | None = None, source: str = "config",
    ) -> list[ToolDefinition]:
        import aiohttp
        self._sse_sessions[name] = {"url": url, "headers": headers or {}}
        base_url = url.replace("/sse", "")

        async with aiohttp.ClientSession(headers=headers) as session:
            init_req = create_initialize_request()
            async with session.post(f"{base_url}/message", json=init_req) as resp:
                init_result = await resp.json()
                parse_response(init_result)

            tools_req = create_tools_list_request()
            async with session.post(f"{base_url}/message", json=tools_req) as resp:
                tools_result_raw = await resp.json()
                tools_result = parse_response(tools_result_raw)

        tool_names = []
        definitions = []
        for t in tools_result.get("tools", []):
            namespaced = f"{name}__{t['name']}"
            tool_names.append(t["name"])
            definitions.append(ToolDefinition(
                name=namespaced,
                description=t.get("description", ""),
                parameters=t.get("inputSchema", {"type": "object", "properties": {}}),
            ))

        self._servers[name] = MCPServerInfo(
            name=name, transport="sse", status="running",
            tools=tool_names, source=source,
        )
        return definitions

    async def stop_server(self, name: str) -> None:
        proc = self._processes.get(name)
        if proc:
            proc.terminate()
            await proc.wait()
        if name in self._servers:
            self._servers[name].status = "stopped"

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any],
    ) -> ToolResult:
        if server_name in self._sse_sessions:
            return await self._call_tool_sse(server_name, tool_name, arguments)

        proc = self._processes.get(server_name)
        if proc is None or proc.returncode is not None:
            return ToolResult(success=False, output=f"MCP server '{server_name}' is not running")
        try:
            req = create_tools_call_request(tool_name, arguments)
            await self._send_stdio(proc, req)
            resp = await self._read_stdio(proc)
            result = parse_response(resp)
            content_parts = result.get("content", [])
            text_parts = [p.get("text", "") for p in content_parts if p.get("type") == "text"]
            return ToolResult(success=True, output="\n".join(text_parts) or str(result))
        except MCPError as e:
            return ToolResult(success=False, output=f"MCP error: {e}")
        except Exception as e:
            return ToolResult(success=False, output=f"MCP call failed: {e}")

    async def _call_tool_sse(
        self, server_name: str, tool_name: str, arguments: dict[str, Any],
    ) -> ToolResult:
        import aiohttp
        session_info = self._sse_sessions[server_name]
        url = session_info["url"].replace("/sse", "")
        req = create_tools_call_request(tool_name, arguments)
        try:
            async with aiohttp.ClientSession(headers=session_info.get("headers")) as session:
                async with session.post(f"{url}/message", json=req) as resp:
                    result_raw = await resp.json()
                    result = parse_response(result_raw)
            content_parts = result.get("content", [])
            text_parts = [p.get("text", "") for p in content_parts if p.get("type") == "text"]
            return ToolResult(success=True, output="\n".join(text_parts) or str(result))
        except Exception as e:
            return ToolResult(success=False, output=f"SSE call failed: {e}")

    async def health_check(self, name: str) -> bool:
        proc = self._processes.get(name)
        return proc is not None and proc.returncode is None

    async def stop_all(self) -> None:
        for name in list(self._servers.keys()):
            await self.stop_server(name)

    async def _send_stdio(self, proc, msg: dict) -> None:
        data = encode_message(msg)
        proc.stdin.write(data)
        await proc.stdin.drain()

    async def _read_stdio(self, proc) -> dict:
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = await proc.stdout.read(1)
            if not chunk:
                raise ConnectionError("MCP server closed connection")
            header += chunk
        header_str = header.decode("utf-8")
        length = int(header_str.split("Content-Length:")[1].split("\r\n")[0].strip())
        body = await proc.stdout.readexactly(length)
        return json.loads(body.decode("utf-8"))
