import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from breadmind.llm.base import ToolDefinition
from breadmind.tools.registry import ToolResult
from breadmind.tools.mcp_protocol import (
    create_initialize_request, create_initialized_notification,
    create_tools_list_request, create_tools_call_request,
    create_resources_list_request, create_resources_read_request,
    create_prompts_list_request, create_prompts_get_request,
    create_logging_set_level_request,
    encode_message, parse_response, MCPError,
)

_MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB
_CONTENT_LENGTH_RE = re.compile(r"Content-Length:\s*(\d+)", re.IGNORECASE)

# Patterns that may indicate prompt injection in tool output
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+all\s+previous", re.IGNORECASE),
    re.compile(r"disregard\s+previous", re.IGNORECASE),
    re.compile(r"^system:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in", re.IGNORECASE),
    re.compile(r"new\s+instructions:", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?previous", re.IGNORECASE),
]

_DEFAULT_MAX_CONCURRENT = 5

ALLOWED_MCP_COMMANDS = {"node", "npx", "python", "python3", "uvx", "docker", "deno", "bun"}


def _check_prompt_injection(text: str) -> bool:
    """Check if text contains patterns that may indicate prompt injection."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _sanitize_output(text: str) -> str:
    """Sanitize tool output: truncate if too large, detect prompt injection."""
    if len(text) > MAX_RESPONSE_SIZE:
        text = text[:MAX_RESPONSE_SIZE] + "\n[...truncated, response exceeded max size]"
    if _check_prompt_injection(text):
        text = "[WARNING: potential prompt injection detected]\n" + text
    return text


@dataclass
class MCPServerInfo:
    name: str
    transport: str
    status: str
    tools: list[str] = field(default_factory=list)
    source: str = "config"


@dataclass
class _StdioServerConfig:
    command: str
    args: list[str]
    env: dict[str, str] | None
    source: str


class MCPClientManager:
    def __init__(self, max_restart_attempts: int = 3, call_timeout: int = 30,
                 max_concurrent: int = _DEFAULT_MAX_CONCURRENT):
        self._servers: dict[str, MCPServerInfo] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._sse_sessions: dict[str, dict] = {}
        self._max_restarts = max_restart_attempts
        self._restart_counts: dict[str, int] = {}
        self._call_timeout = call_timeout
        self._server_configs: dict[str, _StdioServerConfig] = {}
        self._max_concurrent = max_concurrent
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def _get_semaphore(self, server_name: str) -> asyncio.Semaphore:
        if server_name not in self._semaphores:
            self._semaphores[server_name] = asyncio.Semaphore(self._max_concurrent)
        return self._semaphores[server_name]

    def list_servers_sync(self) -> list[MCPServerInfo]:
        return list(self._servers.values())

    async def list_servers(self) -> list[MCPServerInfo]:
        return self.list_servers_sync()

    async def start_stdio_server(
        self, name: str, command: str, args: list[str],
        env: dict[str, str] | None = None, source: str = "config",
    ) -> list[ToolDefinition]:
        # Validate command against allowed list
        cmd_base = Path(command).name.lower() if command else ""
        # Strip common extensions (.exe, .cmd, .bat) for Windows compatibility
        for ext in (".exe", ".cmd", ".bat"):
            if cmd_base.endswith(ext):
                cmd_base = cmd_base[:-len(ext)]
                break
        if cmd_base not in ALLOWED_MCP_COMMANDS:
            raise ValueError(
                f"MCP server command '{command}' not in allowed list: {ALLOWED_MCP_COMMANDS}"
            )

        # Validate args don't contain shell injection
        for arg in args:
            if any(c in arg for c in [';', '&&', '||', '`', '$(']):
                raise ValueError(
                    f"MCP server argument contains suspicious characters: {arg}"
                )

        proc = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._processes[name] = proc
        self._server_configs[name] = _StdioServerConfig(
            command=command, args=args, env=env, source=source,
        )

        init_req = create_initialize_request()
        await self._send_stdio(proc, init_req)
        init_resp = await asyncio.wait_for(
            self._read_stdio(proc), timeout=self._call_timeout,
        )
        parse_response(init_resp)

        notif = create_initialized_notification()
        await self._send_stdio(proc, notif)

        tools_req = create_tools_list_request()
        await self._send_stdio(proc, tools_req)
        tools_resp = await asyncio.wait_for(
            self._read_stdio(proc), timeout=self._call_timeout,
        )
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
        proc = self._processes.pop(name, None)
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        self._sse_sessions.pop(name, None)
        self._server_configs.pop(name, None)
        self._semaphores.pop(name, None)
        if name in self._servers:
            self._servers[name].status = "stopped"

    async def _try_restart_server(self, server_name: str) -> bool:
        cfg = self._server_configs.get(server_name)
        if cfg is None:
            return False
        count = self._restart_counts.get(server_name, 0)
        if count >= self._max_restarts:
            return False
        self._restart_counts[server_name] = count + 1
        try:
            # Clean up old process
            old_proc = self._processes.pop(server_name, None)
            if old_proc and old_proc.returncode is None:
                old_proc.kill()
                await old_proc.wait()
            await self.start_stdio_server(
                server_name, cfg.command, cfg.args, env=cfg.env, source=cfg.source,
            )
            return True
        except Exception:
            return False

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any],
    ) -> ToolResult:
        if server_name in self._sse_sessions:
            return await self._call_tool_sse(server_name, tool_name, arguments)

        proc = self._processes.get(server_name)
        if proc is None or proc.returncode is not None:
            # Attempt auto-restart
            if await self._try_restart_server(server_name):
                proc = self._processes.get(server_name)
            else:
                return ToolResult(success=False, output=f"MCP server '{server_name}' is not running")

        sem = self._get_semaphore(server_name)
        async with sem:
            try:
                req = create_tools_call_request(tool_name, arguments)
                await self._send_stdio(proc, req)
                resp = await asyncio.wait_for(
                    self._read_stdio(proc), timeout=self._call_timeout,
                )
                result = parse_response(resp)
                content_parts = result.get("content", [])
                text_parts = [p.get("text", "") for p in content_parts if p.get("type") == "text"]
                output = "\n".join(text_parts) or str(result)
                output = _sanitize_output(output)
                return ToolResult(success=True, output=output)
            except asyncio.TimeoutError:
                return ToolResult(success=False, output="MCP server timeout")
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
        sem = self._get_semaphore(server_name)
        async with sem:
            try:
                async with aiohttp.ClientSession(headers=session_info.get("headers")) as session:
                    async with asyncio.timeout(self._call_timeout):
                        async with session.post(f"{url}/message", json=req) as resp:
                            result_raw = await resp.json()
                            result = parse_response(result_raw)
                content_parts = result.get("content", [])
                text_parts = [p.get("text", "") for p in content_parts if p.get("type") == "text"]
                output = "\n".join(text_parts) or str(result)
                output = _sanitize_output(output)
                return ToolResult(success=True, output=output)
            except asyncio.TimeoutError:
                return ToolResult(success=False, output="MCP server timeout")
            except Exception as e:
                return ToolResult(success=False, output=f"SSE call failed: {e}")

    async def list_resources(self, server_name: str) -> list[dict]:
        """List available resources from an MCP server."""
        proc = self._processes.get(server_name)
        if proc is None or proc.returncode is not None:
            return []
        req = create_resources_list_request()
        await self._send_stdio(proc, req)
        resp = await asyncio.wait_for(
            self._read_stdio(proc), timeout=self._call_timeout,
        )
        result = parse_response(resp)
        return result.get("resources", [])

    async def read_resource(self, server_name: str, uri: str) -> str:
        """Read a resource by URI."""
        proc = self._processes.get(server_name)
        if proc is None or proc.returncode is not None:
            raise ConnectionError(f"MCP server '{server_name}' is not running")
        req = create_resources_read_request(uri)
        await self._send_stdio(proc, req)
        resp = await asyncio.wait_for(
            self._read_stdio(proc), timeout=self._call_timeout,
        )
        result = parse_response(resp)
        contents = result.get("contents", [])
        if contents:
            return contents[0].get("text", "")
        return ""

    async def list_prompts(self, server_name: str) -> list[dict]:
        """List available prompts from an MCP server."""
        proc = self._processes.get(server_name)
        if proc is None or proc.returncode is not None:
            return []
        req = create_prompts_list_request()
        await self._send_stdio(proc, req)
        resp = await asyncio.wait_for(
            self._read_stdio(proc), timeout=self._call_timeout,
        )
        result = parse_response(resp)
        return result.get("prompts", [])

    async def get_prompt(self, server_name: str, name: str, arguments: dict | None = None) -> str:
        """Get a prompt by name."""
        proc = self._processes.get(server_name)
        if proc is None or proc.returncode is not None:
            raise ConnectionError(f"MCP server '{server_name}' is not running")
        req = create_prompts_get_request(name, arguments)
        await self._send_stdio(proc, req)
        resp = await asyncio.wait_for(
            self._read_stdio(proc), timeout=self._call_timeout,
        )
        result = parse_response(resp)
        messages = result.get("messages", [])
        text_parts = []
        for msg in messages:
            content = msg.get("content", {})
            if isinstance(content, dict) and content.get("type") == "text":
                text_parts.append(content.get("text", ""))
            elif isinstance(content, str):
                text_parts.append(content)
        return "\n".join(text_parts)

    async def set_log_level(self, server_name: str, level: str) -> None:
        """Set logging level on an MCP server."""
        proc = self._processes.get(server_name)
        if proc is None or proc.returncode is not None:
            raise ConnectionError(f"MCP server '{server_name}' is not running")
        req = create_logging_set_level_request(level)
        await self._send_stdio(proc, req)
        resp = await asyncio.wait_for(
            self._read_stdio(proc), timeout=self._call_timeout,
        )
        parse_response(resp)

    async def health_check(self, name: str) -> bool:
        proc = self._processes.get(name)
        return proc is not None and proc.returncode is None

    async def detailed_health_check(self, name: str) -> dict:
        result: dict[str, Any] = {"alive": False, "responsive": False, "tools_count": 0}
        proc = self._processes.get(name)
        if proc is None or proc.returncode is not None:
            return result
        result["alive"] = True
        try:
            req = create_tools_list_request()
            await self._send_stdio(proc, req)
            resp = await asyncio.wait_for(self._read_stdio(proc), timeout=5.0)
            tools_result = parse_response(resp)
            result["responsive"] = True
            result["tools_count"] = len(tools_result.get("tools", []))
        except Exception:
            pass
        return result

    async def stop_all(self) -> None:
        for name in list(self._servers.keys()):
            await self.stop_server(name)

    async def _send_stdio(self, proc: asyncio.subprocess.Process, msg: dict) -> None:
        data = encode_message(msg)
        proc.stdin.write(data)
        await proc.stdin.drain()

    async def _read_stdio(self, proc: asyncio.subprocess.Process) -> dict:
        # Read headers using readline for efficiency
        header_data = b""
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise ConnectionError("MCP server closed connection")
            header_data += line
            if header_data.endswith(b"\r\n\r\n"):
                break

        header_str = header_data.decode("utf-8")
        match = _CONTENT_LENGTH_RE.search(header_str)
        if not match:
            raise ValueError(f"Missing Content-Length header in: {header_str!r}")
        length = int(match.group(1))

        if length > _MAX_MESSAGE_SIZE:
            raise ValueError(
                f"MCP message too large: {length} bytes (max {_MAX_MESSAGE_SIZE})"
            )

        body = await proc.stdout.readexactly(length)
        return json.loads(body.decode("utf-8"))
