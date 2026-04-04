"""Tests for MCPServerManager lifecycle and EventBus integration."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.core.events import EventBus, EventType
from breadmind.mcp.server_manager import (
    MCPServerConfig,
    MCPServerManager,
    MCPServerState,
)
from breadmind.tools.mcp_protocol import encode_message


# ── Helpers ───────────────────────────────────────────────────────────

def _make_frame(payload: dict) -> bytes:
    """Build a Content-Length framed JSON-RPC message."""
    return encode_message(payload)


def _fake_init_response(req_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "test-server", "version": "0.1.0"},
        },
    }


def _fake_tools_response(tools: list[dict], req_id: int = 2) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"tools": tools},
    }


SAMPLE_TOOLS = [
    {"name": "tool_a", "description": "Tool A", "inputSchema": {}},
    {"name": "tool_b", "description": "Tool B", "inputSchema": {}},
]


class FakeStreamReader:
    """Simulate asyncio.StreamReader for subprocess stdout."""

    def __init__(self, frames: list[bytes]) -> None:
        self._buf = b"".join(frames)
        self._pos = 0

    async def readline(self) -> bytes:
        if self._pos >= len(self._buf):
            return b""
        end = self._buf.index(b"\n", self._pos) + 1
        line = self._buf[self._pos : end]
        self._pos = end
        return line

    async def readexactly(self, n: int) -> bytes:
        data = self._buf[self._pos : self._pos + n]
        self._pos += n
        return data


class FakeStreamWriter:
    """Simulate asyncio.StreamWriter for subprocess stdin."""

    def __init__(self) -> None:
        self.written = bytearray()

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        pass


def _build_fake_process(
    responses: list[dict],
    returncode: int = 0,
) -> MagicMock:
    """Create a MagicMock process whose stdout yields the given responses."""
    frames = [_make_frame(r) for r in responses]
    proc = MagicMock()
    proc.stdout = FakeStreamReader(frames)
    proc.stdin = FakeStreamWriter()
    proc.stderr = AsyncMock()
    proc.pid = 12345
    proc.returncode = returncode
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    wait_future: asyncio.Future = asyncio.get_event_loop().create_future()
    wait_future.set_result(0)
    proc.wait = AsyncMock(return_value=0)

    return proc


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def manager(event_bus: EventBus) -> MCPServerManager:
    return MCPServerManager(event_bus)


@pytest.fixture
def sample_config() -> MCPServerConfig:
    return MCPServerConfig(
        name="test-server",
        command="node",
        args=["server.js"],
        env={"API_KEY": "secret"},
    )


# ── Tests: add / remove lifecycle ─────────────────────────────────────

async def test_add_server_success(manager, sample_config, event_bus):
    """Server added successfully: status=running, tools loaded, events emitted."""
    responses = [
        _fake_init_response(),
        _fake_tools_response(SAMPLE_TOOLS),
    ]
    fake_proc = _build_fake_process(responses)

    emitted: list[tuple[str, dict]] = []

    async def capture(data, *, _evt=[]):
        pass

    added_events = []
    tools_events = []
    event_bus.on(EventType.MCP_SERVER_ADDED.value, lambda d: added_events.append(d))
    event_bus.on(EventType.MCP_TOOLS_UPDATED.value, lambda d: tools_events.append(d))

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(sample_config)

    state = await manager.get_server_status("test-server")
    assert state is not None
    assert state.status == "running"
    assert len(state.tools) == 2
    assert state.tools[0]["name"] == "tool_a"

    # Events were emitted
    assert len(added_events) == 1
    assert added_events[0]["name"] == "test-server"
    assert len(tools_events) == 1


async def test_add_server_replaces_existing(manager, sample_config):
    """Adding a server with the same name removes the old one first."""
    responses = [_fake_init_response(), _fake_tools_response(SAMPLE_TOOLS)]
    fake_proc = _build_fake_process(responses)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(sample_config)

    responses2 = [
        _fake_init_response(req_id=10),
        _fake_tools_response([{"name": "new_tool", "description": "New", "inputSchema": {}}], req_id=11),
    ]
    fake_proc2 = _build_fake_process(responses2)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc2):
        await manager.add_server(sample_config)

    state = await manager.get_server_status("test-server")
    assert state.status == "running"
    servers = await manager.list_servers()
    assert len(servers) == 1


async def test_remove_server(manager, sample_config, event_bus):
    """Removing a server stops it, removes from list, and emits events."""
    responses = [_fake_init_response(), _fake_tools_response(SAMPLE_TOOLS)]
    fake_proc = _build_fake_process(responses)

    removed_events = []
    event_bus.on(EventType.MCP_SERVER_REMOVED.value, lambda d: removed_events.append(d))

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(sample_config)

    await manager.remove_server("test-server")

    assert await manager.get_server_status("test-server") is None
    assert len(removed_events) == 1
    assert removed_events[0]["name"] == "test-server"


async def test_remove_nonexistent_server(manager):
    """Removing a server that doesn't exist is a no-op."""
    await manager.remove_server("nonexistent")
    # No error


# ── Tests: restart ────────────────────────────────────────────────────

async def test_restart_server(manager, sample_config):
    """Restart stops then starts the server."""
    responses = [_fake_init_response(), _fake_tools_response(SAMPLE_TOOLS)]
    fake_proc = _build_fake_process(responses)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(sample_config)

    responses2 = [_fake_init_response(req_id=10), _fake_tools_response(SAMPLE_TOOLS, req_id=11)]
    fake_proc2 = _build_fake_process(responses2)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc2):
        await manager.restart_server("test-server")

    state = await manager.get_server_status("test-server")
    assert state.status == "running"


async def test_restart_nonexistent(manager):
    """Restarting a nonexistent server is a no-op."""
    await manager.restart_server("nonexistent")


# ── Tests: get_all_tools aggregation ──────────────────────────────────

async def test_get_all_tools_aggregates(manager):
    """get_all_tools returns tools from all running servers."""
    tools_a = [{"name": "tool_a", "description": "A", "inputSchema": {}}]
    tools_b = [{"name": "tool_b", "description": "B", "inputSchema": {}}]

    proc_a = _build_fake_process([_fake_init_response(), _fake_tools_response(tools_a)])
    proc_b = _build_fake_process([_fake_init_response(req_id=10), _fake_tools_response(tools_b, req_id=11)])

    with patch("asyncio.create_subprocess_exec", return_value=proc_a):
        await manager.add_server(MCPServerConfig(name="srv-a", command="node", args=["a.js"]))

    with patch("asyncio.create_subprocess_exec", return_value=proc_b):
        await manager.add_server(MCPServerConfig(name="srv-b", command="node", args=["b.js"]))

    all_tools = await manager.get_all_tools()
    names = [t["name"] for t in all_tools]
    assert "tool_a" in names
    assert "tool_b" in names
    assert len(all_tools) == 2


# ── Tests: error handling ─────────────────────────────────────────────

async def test_start_failure_sets_error_status(manager, event_bus):
    """If subprocess fails to start, status=error and error event emitted."""
    error_events = []
    event_bus.on(EventType.MCP_SERVER_ERROR.value, lambda d: error_events.append(d))

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("command not found"),
    ):
        await manager.add_server(
            MCPServerConfig(name="bad-server", command="nonexistent-cmd")
        )

    state = await manager.get_server_status("bad-server")
    assert state.status == "error"
    assert "command not found" in state.error

    assert len(error_events) == 1
    assert error_events[0]["name"] == "bad-server"


async def test_init_error_response(manager, event_bus):
    """If MCP initialize returns an error, status=error."""
    error_resp = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32600, "message": "Invalid request"},
    }
    fake_proc = _build_fake_process([error_resp])

    error_events = []
    event_bus.on(EventType.MCP_SERVER_ERROR.value, lambda d: error_events.append(d))

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(
            MCPServerConfig(name="err-server", command="node", args=["bad.js"])
        )

    state = await manager.get_server_status("err-server")
    assert state.status == "error"
    assert len(error_events) == 1


# ── Tests: shutdown_all ───────────────────────────────────────────────

async def test_shutdown_all(manager):
    """shutdown_all stops and removes all servers."""
    proc = _build_fake_process([_fake_init_response(), _fake_tools_response(SAMPLE_TOOLS)])

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        await manager.add_server(MCPServerConfig(name="srv1", command="node"))

    proc2 = _build_fake_process([_fake_init_response(req_id=10), _fake_tools_response([], req_id=11)])

    with patch("asyncio.create_subprocess_exec", return_value=proc2):
        await manager.add_server(MCPServerConfig(name="srv2", command="node"))

    await manager.shutdown_all()
    assert await manager.list_servers() == []


# ── Tests: EventBus-driven operations ─────────────────────────────────

async def test_event_driven_add(manager, event_bus):
    """Emitting mcp_server_add with a dict triggers add_server."""
    responses = [_fake_init_response(), _fake_tools_response(SAMPLE_TOOLS)]
    fake_proc = _build_fake_process(responses)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await event_bus.async_emit("mcp_server_add", {
            "name": "evt-server",
            "command": "node",
            "args": ["srv.js"],
        })

    state = await manager.get_server_status("evt-server")
    assert state is not None
    assert state.status == "running"


async def test_event_driven_remove(manager, event_bus):
    """Emitting mcp_server_remove with a name string triggers remove."""
    responses = [_fake_init_response(), _fake_tools_response(SAMPLE_TOOLS)]
    fake_proc = _build_fake_process(responses)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(MCPServerConfig(name="rm-server", command="node"))

    await event_bus.async_emit("mcp_server_remove", "rm-server")

    assert await manager.get_server_status("rm-server") is None


async def test_event_driven_restart(manager, event_bus):
    """Emitting mcp_server_restart with a dict triggers restart."""
    responses = [_fake_init_response(), _fake_tools_response(SAMPLE_TOOLS)]
    fake_proc = _build_fake_process(responses)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(MCPServerConfig(name="rs-server", command="node"))

    responses2 = [_fake_init_response(req_id=10), _fake_tools_response(SAMPLE_TOOLS, req_id=11)]
    fake_proc2 = _build_fake_process(responses2)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc2):
        await event_bus.async_emit("mcp_server_restart", {"name": "rs-server"})

    state = await manager.get_server_status("rs-server")
    assert state.status == "running"


# ── Tests: call_tool ──────────────────────────────────────────────────

async def test_call_tool_success(manager):
    """call_tool sends a request and returns parsed result."""
    tools = [{"name": "echo", "description": "Echo", "inputSchema": {}}]
    init_and_tools_responses = [_fake_init_response(), _fake_tools_response(tools)]
    fake_proc = _build_fake_process(init_and_tools_responses)

    with patch("asyncio.create_subprocess_exec", return_value=fake_proc):
        await manager.add_server(MCPServerConfig(name="call-srv", command="node"))

    # Now prepare a tool call response on the process
    tool_resp = {"jsonrpc": "2.0", "id": 99, "result": {"content": [{"type": "text", "text": "hello"}]}}
    call_proc_stdout = FakeStreamReader([_make_frame(tool_resp)])

    state = await manager.get_server_status("call-srv")
    # Replace stdout with one that has the tool call response
    state.process.stdout = call_proc_stdout

    result = await manager.call_tool("call-srv", "echo", {"msg": "hello"})
    assert result["content"][0]["text"] == "hello"


async def test_call_tool_server_not_found(manager):
    """call_tool raises ValueError for unknown server."""
    with pytest.raises(ValueError, match="not found"):
        await manager.call_tool("nope", "tool", {})


async def test_call_tool_server_not_running(manager):
    """call_tool raises RuntimeError if server is in error state."""
    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("nope"),
    ):
        await manager.add_server(MCPServerConfig(name="dead", command="nope"))

    with pytest.raises(RuntimeError, match="not running"):
        await manager.call_tool("dead", "tool", {})
