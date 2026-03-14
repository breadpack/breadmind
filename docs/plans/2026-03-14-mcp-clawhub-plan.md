# Sub-project 2: MCP Client + ClawHub + Built-in Tools Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP 프로토콜 클라이언트, ClawHub 스킬 연동, 빌트인 도구를 구현하여 BreadMind 에이전트가 실제 도구를 사용할 수 있게 만든다.

**Architecture:** ToolRegistry를 확장하여 빌트인 도구와 MCP 도구를 통합 관리. MCPClientManager가 stdio/SSE 트랜스포트로 MCP 서버를 연결. RegistrySearchEngine이 ClawHub + MCP Registry에서 스킬을 검색. 메타 도구(mcp_search/install 등)로 LLM이 동적으로 도구를 확장.

**Tech Stack:** Python 3.12+, asyncio, aiohttp, asyncssh, duckduckgo-search, JSON-RPC 2.0 (MCP spec 2024-11-05)

**Spec:** `docs/specs/2026-03-14-mcp-clawhub-design.md`

---

## Chunk 1: MCP Protocol Layer + ToolRegistry 확장

### Task 1: MCP Protocol (JSON-RPC 2.0)

**Files:**
- Create: `src/breadmind/tools/mcp_protocol.py`
- Test: `tests/test_mcp_protocol.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mcp_protocol.py
import pytest
import json
from breadmind.tools.mcp_protocol import (
    MCPMessage, create_initialize_request, create_tools_list_request,
    create_tools_call_request, create_initialized_notification,
    parse_response, MCPError,
)

def test_create_initialize_request():
    msg = create_initialize_request()
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "initialize"
    assert "id" in msg
    assert msg["params"]["protocolVersion"] == "2024-11-05"
    assert "clientInfo" in msg["params"]

def test_create_initialized_notification():
    msg = create_initialized_notification()
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "notifications/initialized"
    assert "id" not in msg  # notifications have no id

def test_create_tools_list_request():
    msg = create_tools_list_request()
    assert msg["method"] == "tools/list"
    assert "id" in msg

def test_create_tools_call_request():
    msg = create_tools_call_request("k8s_list_pods", {"namespace": "default"})
    assert msg["method"] == "tools/call"
    assert msg["params"]["name"] == "k8s_list_pods"
    assert msg["params"]["arguments"] == {"namespace": "default"}

def test_parse_response_success():
    raw = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    result = parse_response(raw)
    assert result == {"tools": []}

def test_parse_response_error():
    raw = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid"}}
    with pytest.raises(MCPError, match="Invalid"):
        parse_response(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_mcp_protocol.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement MCP protocol**

```python
# src/breadmind/tools/mcp_protocol.py
import json
from dataclasses import dataclass
from typing import Any

_request_id = 0

def _next_id() -> int:
    global _request_id
    _request_id += 1
    return _request_id

class MCPError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)

def create_initialize_request() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "breadmind",
                "version": "0.1.0",
            },
        },
    }

def create_initialized_notification() -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }

def create_tools_list_request() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "tools/list",
        "params": {},
    }

def create_tools_call_request(name: str, arguments: dict[str, Any]) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments,
        },
    }

def encode_message(msg: dict) -> bytes:
    """Encode a JSON-RPC message for stdio transport (Content-Length header)."""
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    return header + body

def parse_response(raw: dict) -> Any:
    """Parse a JSON-RPC response, raising MCPError on error responses."""
    if "error" in raw:
        err = raw["error"]
        raise MCPError(err.get("code", -1), err.get("message", "Unknown error"))
    return raw.get("result")
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_mcp_protocol.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/mcp_protocol.py tests/test_mcp_protocol.py
git commit -m "feat: MCP protocol layer with JSON-RPC 2.0 message creation and parsing"
```

---

### Task 2: ToolRegistry 확장 (MCP 도구 통합)

**Files:**
- Modify: `src/breadmind/tools/registry.py`
- Test: `tests/test_registry_mcp.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_registry_mcp.py
import pytest
from unittest.mock import AsyncMock
from breadmind.tools.registry import ToolRegistry, ToolResult, tool
from breadmind.llm.base import ToolDefinition

@tool(description="Builtin echo")
async def echo(message: str) -> str:
    return f"echo: {message}"

def test_register_mcp_tool():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="myserver__list_items",
        description="List items",
        parameters={"type": "object", "properties": {}},
    )
    registry.register_mcp_tool(defn, server_name="myserver")
    assert registry.has_tool("myserver__list_items")
    assert registry.get_tool_source("myserver__list_items") == "mcp:myserver"

def test_unregister_mcp_tools():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="myserver__tool_a",
        description="Tool A",
        parameters={"type": "object", "properties": {}},
    )
    registry.register_mcp_tool(defn, server_name="myserver")
    assert registry.has_tool("myserver__tool_a")
    registry.unregister_mcp_tools("myserver")
    assert not registry.has_tool("myserver__tool_a")

def test_builtin_tool_source():
    registry = ToolRegistry()
    registry.register(echo)
    assert registry.get_tool_source("echo") == "builtin"

def test_mcp_tools_in_definitions():
    registry = ToolRegistry()
    registry.register(echo)
    defn = ToolDefinition(
        name="srv__do_thing",
        description="Do thing",
        parameters={"type": "object", "properties": {}},
    )
    registry.register_mcp_tool(defn, server_name="srv")
    defs = registry.get_all_definitions()
    names = [d.name for d in defs]
    assert "echo" in names
    assert "srv__do_thing" in names

@pytest.mark.asyncio
async def test_execute_mcp_tool_delegates():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="srv__action",
        description="Action",
        parameters={"type": "object", "properties": {}},
    )
    callback = AsyncMock(return_value=ToolResult(success=True, output="mcp result"))
    registry.register_mcp_tool(defn, server_name="srv", execute_callback=callback)
    result = await registry.execute("srv__action", {"key": "val"})
    assert result.success is True
    assert result.output == "mcp result"
    callback.assert_called_once_with("srv", "action", {"key": "val"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_registry_mcp.py -v`
Expected: FAIL

- [ ] **Step 3: Extend ToolRegistry**

```python
# src/breadmind/tools/registry.py
import inspect
import asyncio
from dataclasses import dataclass
from typing import Any, Callable
from breadmind.llm.base import ToolDefinition


@dataclass
class ToolResult:
    success: bool
    output: str


def tool(description: str):
    """Decorator to register a function as an agent tool."""
    def decorator(func: Callable):
        sig = inspect.signature(func)
        properties = {}
        required = []
        for name, param in sig.parameters.items():
            prop = {"type": "string"}
            annotation = param.annotation
            if annotation == int:
                prop = {"type": "integer"}
            elif annotation == float:
                prop = {"type": "number"}
            elif annotation == bool:
                prop = {"type": "boolean"}
            properties[name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(name)

        func._tool_definition = ToolDefinition(
            name=func.__name__,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )
        return func
    return decorator


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._mcp_tools: dict[str, str] = {}  # tool_name -> server_name
        self._mcp_callback: Callable | None = None

    def register(self, func: Callable):
        defn = getattr(func, "_tool_definition", None)
        if defn is None:
            raise ValueError(f"{func.__name__} is not decorated with @tool")
        self._tools[defn.name] = func
        self._definitions[defn.name] = defn

    def register_mcp_tool(
        self,
        definition: ToolDefinition,
        server_name: str,
        execute_callback: Callable | None = None,
    ):
        self._definitions[definition.name] = definition
        self._mcp_tools[definition.name] = server_name
        if execute_callback:
            self._mcp_callback = execute_callback

    def unregister_mcp_tools(self, server_name: str):
        to_remove = [
            name for name, srv in self._mcp_tools.items() if srv == server_name
        ]
        for name in to_remove:
            self._definitions.pop(name, None)
            self._mcp_tools.pop(name, None)

    def get_all_definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def has_tool(self, name: str) -> bool:
        return name in self._tools or name in self._mcp_tools

    def get_tool_source(self, name: str) -> str:
        if name in self._tools:
            return "builtin"
        server = self._mcp_tools.get(name)
        if server:
            return f"mcp:{server}"
        return "unknown"

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        # Check builtin first
        func = self._tools.get(name)
        if func is not None:
            try:
                if asyncio.iscoroutinefunction(func):
                    output = await func(**arguments)
                else:
                    output = func(**arguments)
                return ToolResult(success=True, output=str(output))
            except Exception as e:
                return ToolResult(success=False, output=f"Tool error: {e}")

        # Check MCP tool
        server_name = self._mcp_tools.get(name)
        if server_name is not None and self._mcp_callback:
            # Strip server prefix to get original tool name
            original_name = name.split("__", 1)[1] if "__" in name else name
            return await self._mcp_callback(server_name, original_name, arguments)

        return ToolResult(success=False, output=f"Tool not found: {name}")
```

- [ ] **Step 4: Run tests (new + existing)**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_registry_mcp.py tests/test_tools.py tests/test_agent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/registry.py tests/test_registry_mcp.py
git commit -m "feat: extend ToolRegistry with MCP tool registration and delegation"
```

---

## Chunk 2: MCP Client Manager

### Task 3: Stdio Transport

**Files:**
- Create: `src/breadmind/tools/mcp_client.py`
- Test: `tests/test_mcp_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mcp_client.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.tools.mcp_client import MCPClientManager, MCPServerInfo

@pytest.fixture
def manager():
    return MCPClientManager()

def test_manager_initial_state(manager):
    assert manager.list_servers_sync() == []

@pytest.mark.asyncio
async def test_start_stdio_server(manager):
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdout = MagicMock()
    mock_proc.pid = 12345

    # Mock reading initialize response + tools/list response
    init_response = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "test-server"}}
    })
    tools_response = json.dumps({
        "jsonrpc": "2.0", "id": 3,
        "result": {"tools": [
            {"name": "do_thing", "description": "Does a thing", "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}}}
        ]}
    })
    responses = iter([
        f"Content-Length: {len(init_response.encode())}\r\n\r\n{init_response}".encode(),
        b"",  # for initialized notification (no response)
        f"Content-Length: {len(tools_response.encode())}\r\n\r\n{tools_response}".encode(),
    ])

    async def mock_read(n):
        try:
            return next(responses)
        except StopIteration:
            return b""

    mock_proc.stdout.read = mock_read

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        await manager.start_stdio_server("test", "echo", ["hello"])

    servers = manager.list_servers_sync()
    assert len(servers) == 1
    assert servers[0].name == "test"
    assert servers[0].status == "running"
    assert "do_thing" in servers[0].tools

@pytest.mark.asyncio
async def test_stop_server(manager):
    manager._servers["test"] = MCPServerInfo(
        name="test", transport="stdio", status="running", tools=[], source="config"
    )
    manager._processes["test"] = MagicMock()
    manager._processes["test"].terminate = MagicMock()
    manager._processes["test"].wait = AsyncMock()

    await manager.stop_server("test")
    assert manager._servers["test"].status == "stopped"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_mcp_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implement MCPClientManager**

```python
# src/breadmind/tools/mcp_client.py
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
    transport: str          # "stdio" | "sse"
    status: str             # "running" | "stopped" | "error"
    tools: list[str] = field(default_factory=list)
    source: str = "config"  # "clawhub" | "config" | "manual"


class MCPClientManager:
    def __init__(self, max_restart_attempts: int = 3):
        self._servers: dict[str, MCPServerInfo] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._max_restarts = max_restart_attempts
        self._restart_counts: dict[str, int] = {}

    def list_servers_sync(self) -> list[MCPServerInfo]:
        return list(self._servers.values())

    async def list_servers(self) -> list[MCPServerInfo]:
        return self.list_servers_sync()

    async def start_stdio_server(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        source: str = "config",
    ) -> list[ToolDefinition]:
        proc = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._processes[name] = proc

        # Initialize handshake
        init_req = create_initialize_request()
        await self._send_stdio(proc, init_req)
        init_resp = await self._read_stdio(proc)
        parse_response(init_resp)

        # Send initialized notification
        notif = create_initialized_notification()
        await self._send_stdio(proc, notif)

        # Discover tools
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

    async def stop_server(self, name: str) -> None:
        proc = self._processes.get(name)
        if proc:
            proc.terminate()
            await proc.wait()
        if name in self._servers:
            self._servers[name].status = "stopped"

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResult:
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

    async def health_check(self, name: str) -> bool:
        proc = self._processes.get(name)
        return proc is not None and proc.returncode is None

    async def stop_all(self) -> None:
        for name in list(self._servers.keys()):
            await self.stop_server(name)

    async def _send_stdio(self, proc: asyncio.subprocess.Process, msg: dict) -> None:
        data = encode_message(msg)
        proc.stdin.write(data)
        await proc.stdin.drain()

    async def _read_stdio(self, proc: asyncio.subprocess.Process) -> dict:
        # Read Content-Length header
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
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_mcp_client.py -v`
Expected: PASS (some may need mock adjustments — fix and re-run)

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: MCP client manager with stdio transport and lifecycle management"
```

---

### Task 4: SSE Transport

**Files:**
- Modify: `src/breadmind/tools/mcp_client.py`
- Test: `tests/test_mcp_sse.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mcp_sse.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.tools.mcp_client import MCPClientManager

@pytest.mark.asyncio
async def test_connect_sse_server():
    manager = MCPClientManager()

    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200

    # Mock SSE event stream for initialize response
    async def mock_iter():
        yield MagicMock(
            data='{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"remote"}}}',
            event="message",
        )
        yield MagicMock(
            data='{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"remote_tool","description":"A remote tool","inputSchema":{"type":"object","properties":{}}}]}}',
            event="message",
        )

    mock_resp.__aiter__ = mock_iter
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession") as MockSession:
        session_instance = MagicMock()
        session_instance.get = MagicMock(return_value=mock_resp)
        session_instance.post = AsyncMock(return_value=MagicMock(
            json=AsyncMock(return_value={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}),
            status=200,
        ))
        session_instance.__aenter__ = AsyncMock(return_value=session_instance)
        session_instance.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value = session_instance

        await manager.connect_sse_server("remote", "http://localhost:3001/sse")

    servers = manager.list_servers_sync()
    assert len(servers) == 1
    assert servers[0].name == "remote"
    assert servers[0].transport == "sse"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_mcp_sse.py -v`
Expected: FAIL

- [ ] **Step 3: Add SSE transport to MCPClientManager**

Add these methods to `MCPClientManager` in `src/breadmind/tools/mcp_client.py`:

```python
    async def connect_sse_server(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
        source: str = "config",
    ) -> list[ToolDefinition]:
        import aiohttp

        self._sse_sessions[name] = {"url": url, "headers": headers or {}}

        # SSE transport: POST JSON-RPC to the server's HTTP endpoint
        base_url = url.replace("/sse", "")
        async with aiohttp.ClientSession(headers=headers) as session:
            # Initialize
            init_req = create_initialize_request()
            async with session.post(f"{base_url}/message", json=init_req) as resp:
                init_result = await resp.json()
                parse_response(init_result)

            # Discover tools
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
```

Also add `self._sse_sessions: dict[str, dict] = {}` to `__init__`, and extend `call_tool` to handle SSE servers:

```python
    async def call_tool(self, server_name, tool_name, arguments):
        # SSE path
        if server_name in self._sse_sessions:
            return await self._call_tool_sse(server_name, tool_name, arguments)
        # stdio path (existing)
        ...

    async def _call_tool_sse(self, server_name, tool_name, arguments):
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
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_mcp_sse.py tests/test_mcp_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/mcp_client.py tests/test_mcp_sse.py
git commit -m "feat: SSE transport support for external MCP servers"
```

---

## Chunk 3: Built-in Tools

### Task 5: Built-in Tools (shell_exec, web_search, file_read, file_write)

**Files:**
- Create: `src/breadmind/tools/builtin.py`
- Test: `tests/test_builtin_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_builtin_tools.py
import pytest
import os
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.tools.builtin import shell_exec, web_search, file_read, file_write

@pytest.mark.asyncio
async def test_shell_exec_local():
    result = await shell_exec(command="echo hello", host="localhost", timeout=5)
    assert "hello" in result

@pytest.mark.asyncio
async def test_shell_exec_timeout():
    # Use a command that sleeps longer than timeout
    with pytest.raises(Exception):
        await shell_exec(command="ping -n 10 127.0.0.1", host="localhost", timeout=1)

@pytest.mark.asyncio
async def test_file_read_write():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test content")
        path = f.name
    try:
        content = await file_read(path=path)
        assert content == "test content"

        await file_write(path=path, content="new content")
        content2 = await file_read(path=path)
        assert content2 == "new content"
    finally:
        os.unlink(path)

@pytest.mark.asyncio
async def test_file_read_not_found():
    result = await file_read(path="/nonexistent/path/file.txt")
    assert "error" in result.lower() or "not found" in result.lower()

@pytest.mark.asyncio
async def test_web_search():
    with patch("breadmind.tools.builtin._duckduckgo_search", new_callable=AsyncMock) as mock:
        mock.return_value = [
            {"title": "Result 1", "href": "http://example.com", "body": "Description 1"}
        ]
        result = await web_search(query="test query", limit=1)
        assert "Result 1" in result

def test_tools_have_definitions():
    assert hasattr(shell_exec, "_tool_definition")
    assert hasattr(web_search, "_tool_definition")
    assert hasattr(file_read, "_tool_definition")
    assert hasattr(file_write, "_tool_definition")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_builtin_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement built-in tools**

```python
# src/breadmind/tools/builtin.py
import asyncio
import os
from pathlib import Path
from breadmind.tools.registry import tool


@tool(description="Execute a shell command locally or via SSH. Use host='localhost' for local commands.")
async def shell_exec(command: str, host: str = "localhost", timeout: int = 30) -> str:
    if host == "localhost":
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command timed out after {timeout}s: {command}")
        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")
        result = output
        if errors:
            result += f"\nSTDERR: {errors}"
        if proc.returncode != 0:
            result += f"\nExit code: {proc.returncode}"
        return result.strip()
    else:
        # Remote SSH execution
        try:
            import asyncssh
        except ImportError:
            return "Error: asyncssh not installed. Install with: pip install asyncssh"
        try:
            async with asyncssh.connect(host) as conn:
                result = await asyncio.wait_for(conn.run(command), timeout=timeout)
                output = result.stdout or ""
                if result.stderr:
                    output += f"\nSTDERR: {result.stderr}"
                return output.strip()
        except Exception as e:
            return f"SSH error: {e}"


@tool(description="Search the web for information using DuckDuckGo")
async def web_search(query: str, limit: int = 5) -> str:
    results = await _duckduckgo_search(query, limit)
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"**{r.get('title', 'No title')}**")
        lines.append(f"  URL: {r.get('href', '')}")
        lines.append(f"  {r.get('body', '')}")
        lines.append("")
    return "\n".join(lines).strip()


async def _duckduckgo_search(query: str, limit: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=limit))
            return results
    except ImportError:
        return [{"title": "Error", "href": "", "body": "duckduckgo-search not installed"}]
    except Exception as e:
        return [{"title": "Error", "href": "", "body": str(e)}]


@tool(description="Read content from a file")
async def file_read(path: str, encoding: str = "utf-8") -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: File not found: {path}"
        return p.read_text(encoding=encoding)
    except Exception as e:
        return f"Error reading file: {e}"


@tool(description="Write content to a file")
async def file_write(path: str, content: str, encoding: str = "utf-8") -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"
```

- [ ] **Step 4: Add duckduckgo-search to dependencies**

Add to `pyproject.toml` dependencies:
```
    "duckduckgo-search>=7.0.0",
    "asyncssh>=2.17.0",
```

Run: `cd D:/Projects/breadmind && pip install -e ".[dev]"`

- [ ] **Step 5: Run tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_builtin_tools.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/tools/builtin.py tests/test_builtin_tools.py pyproject.toml
git commit -m "feat: built-in tools (shell_exec, web_search, file_read, file_write)"
```

---

## Chunk 4: Registry Search Engine + Meta Tools

### Task 6: Registry Search Engine

**Files:**
- Create: `src/breadmind/tools/registry_search.py`
- Test: `tests/test_registry_search.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_registry_search.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.tools.registry_search import (
    RegistrySearchEngine, RegistrySearchResult, RegistryConfig,
)

@pytest.fixture
def engine():
    configs = [
        RegistryConfig(name="clawhub", type="clawhub", enabled=True),
        RegistryConfig(name="mcp-registry", type="mcp_registry",
                       url="https://registry.modelcontextprotocol.io", enabled=True),
    ]
    return RegistrySearchEngine(configs)

@pytest.mark.asyncio
async def test_search_returns_results(engine):
    with patch.object(engine, "_search_clawhub", new_callable=AsyncMock) as mock_ch, \
         patch.object(engine, "_search_mcp_registry", new_callable=AsyncMock) as mock_mr:
        mock_ch.return_value = [
            RegistrySearchResult(
                name="mcp-proxmox", slug="mcp-proxmox",
                description="Proxmox MCP server", source="clawhub",
                install_command="clawhub install mcp-proxmox",
            )
        ]
        mock_mr.return_value = [
            RegistrySearchResult(
                name="proxmox-mcp-plus", slug="proxmox-mcp-plus",
                description="Another Proxmox MCP", source="mcp_registry",
                install_command=None,
            )
        ]
        results = await engine.search("proxmox")
        assert len(results) == 2
        assert results[0].source == "clawhub"

@pytest.mark.asyncio
async def test_search_deduplicates(engine):
    with patch.object(engine, "_search_clawhub", new_callable=AsyncMock) as mock_ch, \
         patch.object(engine, "_search_mcp_registry", new_callable=AsyncMock) as mock_mr:
        mock_ch.return_value = [
            RegistrySearchResult(name="my-tool", slug="my-tool",
                                 description="A tool", source="clawhub", install_command=None)
        ]
        mock_mr.return_value = [
            RegistrySearchResult(name="my-tool", slug="my-tool",
                                 description="A tool", source="mcp_registry", install_command=None)
        ]
        results = await engine.search("tool")
        assert len(results) == 1  # deduplicated

@pytest.mark.asyncio
async def test_search_skips_failed_registry(engine):
    with patch.object(engine, "_search_clawhub", new_callable=AsyncMock) as mock_ch, \
         patch.object(engine, "_search_mcp_registry", new_callable=AsyncMock) as mock_mr:
        mock_ch.side_effect = Exception("API down")
        mock_mr.return_value = [
            RegistrySearchResult(name="tool", slug="tool",
                                 description="Works", source="mcp_registry", install_command=None)
        ]
        results = await engine.search("tool")
        assert len(results) == 1

@pytest.mark.asyncio
async def test_disabled_registry_skipped():
    configs = [
        RegistryConfig(name="clawhub", type="clawhub", enabled=False),
    ]
    engine = RegistrySearchEngine(configs)
    results = await engine.search("anything")
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_registry_search.py -v`
Expected: FAIL

- [ ] **Step 3: Implement RegistrySearchEngine**

```python
# src/breadmind/tools/registry_search.py
import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class RegistryConfig:
    name: str
    type: str                # "clawhub" | "mcp_registry" | "custom"
    enabled: bool = True
    url: str | None = None


@dataclass
class RegistrySearchResult:
    name: str
    slug: str
    description: str
    source: str
    install_command: str | None


class RegistrySearchEngine:
    def __init__(self, registries: list[RegistryConfig]):
        self._registries = registries

    async def search(self, query: str, limit: int = 10) -> list[RegistrySearchResult]:
        tasks = []
        for reg in self._registries:
            if not reg.enabled:
                continue
            if reg.type == "clawhub":
                tasks.append(self._safe_search(self._search_clawhub, query, limit))
            elif reg.type == "mcp_registry":
                tasks.append(self._safe_search(self._search_mcp_registry, query, limit))

        all_results = await asyncio.gather(*tasks)
        merged = []
        seen_names = set()
        for results in all_results:
            for r in results:
                if r.name not in seen_names:
                    seen_names.add(r.name)
                    merged.append(r)
        return merged[:limit]

    async def _safe_search(self, func, query, limit) -> list[RegistrySearchResult]:
        try:
            return await func(query, limit)
        except Exception:
            return []

    async def _search_clawhub(self, query: str, limit: int) -> list[RegistrySearchResult]:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://clawhub.ai/api/search",
                params={"q": query, "limit": limit},
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [
                    RegistrySearchResult(
                        name=item.get("name", ""),
                        slug=item.get("slug", ""),
                        description=item.get("description", ""),
                        source="clawhub",
                        install_command=f"clawhub install {item.get('slug', '')}",
                    )
                    for item in data.get("results", [])
                ]

    async def _search_mcp_registry(self, query: str, limit: int) -> list[RegistrySearchResult]:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://registry.modelcontextprotocol.io/api/search",
                params={"q": query, "limit": limit},
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [
                    RegistrySearchResult(
                        name=item.get("name", ""),
                        slug=item.get("slug", item.get("name", "")),
                        description=item.get("description", ""),
                        source="mcp_registry",
                        install_command=None,
                    )
                    for item in data.get("results", data.get("servers", []))
                ]
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_registry_search.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/registry_search.py tests/test_registry_search.py
git commit -m "feat: registry search engine with ClawHub and MCP Registry adapters"
```

---

### Task 7: Meta Tools (mcp_search, mcp_install, etc.)

**Files:**
- Create: `src/breadmind/tools/meta.py`
- Test: `tests/test_meta_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_meta_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.meta import create_meta_tools
from breadmind.tools.mcp_client import MCPClientManager, MCPServerInfo
from breadmind.tools.registry_search import (
    RegistrySearchEngine, RegistrySearchResult, RegistryConfig,
)

@pytest.fixture
def meta_tools():
    manager = MCPClientManager()
    engine = RegistrySearchEngine([])
    tools = create_meta_tools(manager, engine)
    return tools, manager, engine

def test_create_meta_tools_returns_dict(meta_tools):
    tools, _, _ = meta_tools
    assert "mcp_search" in tools
    assert "mcp_install" in tools
    assert "mcp_uninstall" in tools
    assert "mcp_list" in tools
    assert "mcp_recommend" in tools
    for func in tools.values():
        assert hasattr(func, "_tool_definition")

@pytest.mark.asyncio
async def test_mcp_search(meta_tools):
    tools, _, engine = meta_tools
    engine.search = AsyncMock(return_value=[
        RegistrySearchResult(
            name="test-mcp", slug="test-mcp",
            description="A test MCP server", source="clawhub",
            install_command="clawhub install test-mcp",
        )
    ])
    result = await tools["mcp_search"](query="test")
    assert "test-mcp" in result

@pytest.mark.asyncio
async def test_mcp_list(meta_tools):
    tools, manager, _ = meta_tools
    manager._servers["my-server"] = MCPServerInfo(
        name="my-server", transport="stdio", status="running",
        tools=["tool_a"], source="config",
    )
    result = await tools["mcp_list"]()
    assert "my-server" in result
    assert "running" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_meta_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement meta tools**

```python
# src/breadmind/tools/meta.py
import json
from breadmind.tools.registry import tool
from breadmind.tools.mcp_client import MCPClientManager
from breadmind.tools.registry_search import RegistrySearchEngine


def create_meta_tools(
    mcp_manager: MCPClientManager,
    search_engine: RegistrySearchEngine,
) -> dict:
    """Create meta tools for MCP management. Returns dict of name -> decorated function."""

    @tool(description="Search MCP skill registries for tools matching a query")
    async def mcp_search(query: str, limit: int = 5) -> str:
        results = await search_engine.search(query, limit)
        if not results:
            return "No MCP skills found matching your query."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.name}** ({r.source})")
            lines.append(f"   {r.description}")
            if r.install_command:
                lines.append(f"   Install: {r.install_command}")
        return "\n".join(lines)

    @tool(description="Recommend MCP skills based on search results and explain their relevance")
    async def mcp_recommend(query: str) -> str:
        results = await search_engine.search(query, limit=5)
        if not results:
            return "No relevant MCP skills found to recommend."
        lines = ["Here are recommended MCP skills for your needs:\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.name}** — {r.description}")
            lines.append(f"   Source: {r.source}")
        lines.append("\nWould you like me to install any of these?")
        return "\n".join(lines)

    @tool(description="Install an MCP skill from a registry. Requires user approval.")
    async def mcp_install(slug: str, source: str = "clawhub") -> str:
        # For ClawHub, use clawhub CLI or HTTP fallback
        import asyncio
        try:
            proc = await asyncio.create_subprocess_exec(
                "clawhub", "install", slug,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return f"Install failed: {stderr.decode()}"

            # Start the installed MCP server
            # Determine command from installed skill metadata
            skill_dir = f"./skills/{slug}"
            definitions = await mcp_manager.start_stdio_server(
                name=slug,
                command="node",  # Default; real impl parses SKILL.md
                args=[f"{skill_dir}/index.js"],
                source="clawhub",
            )
            tool_names = [d.name for d in definitions]
            return f"Installed and started '{slug}'. Available tools: {', '.join(tool_names)}"
        except FileNotFoundError:
            return "Error: clawhub CLI not found. Install it first."
        except Exception as e:
            return f"Install error: {e}"

    @tool(description="Uninstall an MCP skill. Requires user approval.")
    async def mcp_uninstall(name: str) -> str:
        try:
            await mcp_manager.stop_server(name)
            return f"Stopped and uninstalled MCP server '{name}'."
        except Exception as e:
            return f"Uninstall error: {e}"

    @tool(description="List all installed and connected MCP servers")
    async def mcp_list() -> str:
        servers = await mcp_manager.list_servers()
        if not servers:
            return "No MCP servers installed or connected."
        lines = []
        for s in servers:
            tools_str = ", ".join(s.tools) if s.tools else "none"
            lines.append(f"- **{s.name}** [{s.transport}] status={s.status} source={s.source}")
            lines.append(f"  Tools: {tools_str}")
        return "\n".join(lines)

    @tool(description="Start a stopped MCP server")
    async def mcp_start(name: str) -> str:
        return f"Start not implemented for '{name}' — server config needed from DB."

    @tool(description="Stop a running MCP server")
    async def mcp_stop(name: str) -> str:
        try:
            await mcp_manager.stop_server(name)
            return f"Stopped MCP server '{name}'."
        except Exception as e:
            return f"Stop error: {e}"

    return {
        "mcp_search": mcp_search,
        "mcp_install": mcp_install,
        "mcp_uninstall": mcp_uninstall,
        "mcp_list": mcp_list,
        "mcp_recommend": mcp_recommend,
        "mcp_start": mcp_start,
        "mcp_stop": mcp_stop,
    }
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_meta_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/meta.py tests/test_meta_tools.py
git commit -m "feat: MCP meta tools (search, install, uninstall, list, recommend)"
```

---

## Chunk 5: Config Extension + Main Wiring

### Task 8: Config Extension (MCPConfig)

**Files:**
- Modify: `src/breadmind/config.py`
- Test: `tests/test_config_mcp.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config_mcp.py
import pytest
import tempfile
import os
from pathlib import Path
from breadmind.config import load_config, MCPConfig, RegistryConfigItem

def test_mcp_config_defaults():
    cfg = MCPConfig()
    assert cfg.auto_discover is True
    assert cfg.max_restart_attempts == 3
    assert cfg.servers == {}
    assert len(cfg.registries) == 2  # clawhub + mcp-registry

def test_load_config_with_mcp(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
llm:
  default_provider: ollama
mcp:
  auto_discover: false
  max_restart_attempts: 5
  servers:
    my-server:
      transport: sse
      url: http://localhost:3001/sse
  registries:
    - name: clawhub
      type: clawhub
      enabled: true
""")
    cfg = load_config(str(tmp_path))
    assert cfg.mcp.auto_discover is False
    assert cfg.mcp.max_restart_attempts == 5
    assert "my-server" in cfg.mcp.servers
    assert cfg.mcp.servers["my-server"]["transport"] == "sse"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_config_mcp.py -v`
Expected: FAIL

- [ ] **Step 3: Extend config.py**

Add `MCPConfig`, `RegistryConfigItem` dataclasses and update `AppConfig` and `load_config` in `src/breadmind/config.py`:

```python
@dataclass
class RegistryConfigItem:
    name: str
    type: str
    enabled: bool = True
    url: str | None = None

@dataclass
class MCPConfig:
    auto_discover: bool = True
    max_restart_attempts: int = 3
    servers: dict = field(default_factory=dict)
    registries: list[RegistryConfigItem] = field(default_factory=lambda: [
        RegistryConfigItem(name="clawhub", type="clawhub", enabled=True),
        RegistryConfigItem(name="mcp-registry", type="mcp_registry", enabled=True,
                           url="https://registry.modelcontextprotocol.io"),
    ])

@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
```

Update `load_config` to parse MCP section:

```python
def load_config(config_dir: str = "config") -> AppConfig:
    ...
    mcp_raw = raw.get("mcp", {})
    mcp_config = MCPConfig()
    if mcp_raw:
        mcp_config.auto_discover = mcp_raw.get("auto_discover", True)
        mcp_config.max_restart_attempts = mcp_raw.get("max_restart_attempts", 3)
        mcp_config.servers = mcp_raw.get("servers", {})
        if "registries" in mcp_raw:
            mcp_config.registries = [
                RegistryConfigItem(**r) for r in mcp_raw["registries"]
            ]

    return AppConfig(
        llm=LLMConfig(...),
        database=DatabaseConfig(...),
        mcp=mcp_config,
    )
```

- [ ] **Step 4: Run tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_config_mcp.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/config.py tests/test_config_mcp.py
git commit -m "feat: MCPConfig with registry list and server configuration"
```

---

### Task 9: Wire Everything in main.py

**Files:**
- Modify: `src/breadmind/main.py`
- Modify: `config/safety.yaml`

- [ ] **Step 1: Update main.py**

```python
# src/breadmind/main.py
import asyncio
from breadmind.config import load_config, load_safety_config
from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.ollama import OllamaProvider
from breadmind.tools.registry import ToolRegistry
from breadmind.tools.builtin import shell_exec, web_search, file_read, file_write
from breadmind.tools.mcp_client import MCPClientManager
from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig
from breadmind.tools.meta import create_meta_tools


def create_provider(config):
    provider_name = config.llm.default_provider
    if provider_name == "claude":
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not set, falling back to ollama")
            return OllamaProvider()
        return ClaudeProvider(api_key=api_key, default_model=config.llm.default_model)
    elif provider_name == "ollama":
        return OllamaProvider()
    else:
        return OllamaProvider()


async def run():
    config = load_config()
    safety_cfg = load_safety_config()

    provider = create_provider(config)
    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    # Register built-in tools
    for t in [shell_exec, web_search, file_read, file_write]:
        registry.register(t)

    # Initialize MCP
    mcp_manager = MCPClientManager(max_restart_attempts=config.mcp.max_restart_attempts)

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

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        max_turns=config.llm.tool_call_max_turns,
    )

    print("BreadMind v0.1.0 - AI Infrastructure Agent")
    print(f"  Built-in tools: {len([t for t in registry.get_all_definitions() if registry.get_tool_source(t.name) == 'builtin'])}")
    print(f"  Meta tools: {len(meta_tools)}")
    print(f"  MCP servers: {len(config.mcp.servers)}")
    print("Type 'quit' to exit.\n")

    try:
        while True:
            try:
                user_input = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input.lower() in ("quit", "exit"):
                break

            response = await agent.handle_message(user_input, user="local", channel="cli")
            print(f"breadmind> {response}\n")
    finally:
        await mcp_manager.stop_all()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update safety.yaml**

Add `mcp_recommend` to require_approval exemption — it's already allowed. Verify existing entries:

```yaml
# config/safety.yaml (no changes needed — mcp_install/mcp_uninstall already listed)
```

- [ ] **Step 3: Run all tests**

Run: `cd D:/Projects/breadmind && python -m pytest -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/main.py
git commit -m "feat: wire MCP client, built-in tools, and meta tools into main entry point"
```

---

### Task 10: Integration Smoke Test

- [ ] **Step 1: Run full test suite**

Run: `cd D:/Projects/breadmind && python -m pytest -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Verify CLI starts**

Run: `cd D:/Projects/breadmind && echo "quit" | python -m breadmind.main`
Expected: Shows "BreadMind v0.1.0" with tool/server counts, then exits

- [ ] **Step 3: Commit and push**

```bash
git add -A
git commit -m "chore: sub-project 2 complete — MCP client, ClawHub, built-in tools"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | MCP Protocol (JSON-RPC 2.0) | `tools/mcp_protocol.py` |
| 2 | ToolRegistry 확장 (MCP 통합) | `tools/registry.py` (수정) |
| 3 | MCP Client Manager (stdio) | `tools/mcp_client.py` |
| 4 | SSE Transport | `tools/mcp_client.py` (확장) |
| 5 | Built-in Tools | `tools/builtin.py` |
| 6 | Registry Search Engine | `tools/registry_search.py` |
| 7 | Meta Tools | `tools/meta.py` |
| 8 | Config Extension (MCPConfig) | `config.py` (수정) |
| 9 | Main Wiring | `main.py` (수정) |
| 10 | Integration Smoke Test | — |

**Dependency graph:**
- Task 1 → Task 3, 4 (protocol needed by client)
- Task 2 → Task 3, 4, 7 (registry needed by client and meta tools)
- Task 3 → Task 7 (client needed by meta tools)
- Task 5 → Task 9 (builtin tools needed by main)
- Task 6 → Task 7 (search engine needed by meta tools)
- Task 8 → Task 9 (config needed by main)
- Tasks 1-8 → Task 9 → Task 10
