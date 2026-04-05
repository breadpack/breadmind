"""Tests for Client/Server Architecture Split."""

from __future__ import annotations

import pytest

from breadmind.core.client_server import (
    ClientConfig,
    InferenceClient,
    InferenceServer,
    ServerConfig,
)


class TestInferenceServer:
    async def test_start_stop(self):
        server = InferenceServer()
        assert not server.running
        await server.start()
        assert server.running
        await server.stop()
        assert not server.running

    async def test_handle_request(self):
        server = InferenceServer()
        await server.start()
        result = await server.handle_request("s1", "hello")
        assert result["session_id"] == "s1"
        assert "hello" in result["response"]
        assert server.active_sessions == 1

    async def test_handle_request_not_running_raises(self):
        server = InferenceServer()
        with pytest.raises(RuntimeError, match="not running"):
            await server.handle_request("s1", "hello")

    async def test_max_sessions_enforced(self):
        config = ServerConfig(max_sessions=1)
        server = InferenceServer(config)
        await server.start()
        await server.handle_request("s1", "hello")
        with pytest.raises(RuntimeError, match="Maximum sessions"):
            await server.handle_request("s2", "world")

    async def test_stream_response(self):
        server = InferenceServer()
        await server.start()
        chunks = [c async for c in server.stream_response("s1", "hello world")]
        assert len(chunks) == 2
        assert chunks[0]["chunk"] == "hello"
        assert chunks[1]["chunk"] == "world"

    async def test_stop_clears_sessions(self):
        server = InferenceServer()
        await server.start()
        await server.handle_request("s1", "hi")
        assert server.active_sessions == 1
        await server.stop()
        assert server.active_sessions == 0


class TestInferenceClient:
    async def test_connect(self):
        client = InferenceClient()
        assert not client.connected
        await client.connect()
        assert client.connected

    async def test_connect_empty_url_raises(self):
        client = InferenceClient(ClientConfig(server_url=""))
        with pytest.raises(ValueError, match="Server URL"):
            await client.connect()

    async def test_send_prompt_requires_connection(self):
        client = InferenceClient()
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.send_prompt("hello")

    async def test_send_prompt(self):
        client = InferenceClient()
        await client.connect()
        result = await client.send_prompt("hello")
        assert "hello" in result["response"]

    async def test_stream_prompt(self):
        client = InferenceClient()
        await client.connect()
        chunks = [c async for c in client.stream_prompt("a b c")]
        assert len(chunks) == 3

    async def test_disconnect(self):
        client = InferenceClient()
        await client.connect()
        await client.disconnect()
        assert not client.connected
