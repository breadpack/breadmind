import pytest
import json
import threading
from breadmind.tools.mcp_protocol import (
    create_initialize_request, create_tools_list_request,
    create_tools_call_request, create_initialized_notification,
    create_resources_list_request, create_resources_read_request,
    create_prompts_list_request, create_prompts_get_request,
    create_logging_set_level_request,
    parse_response, MCPError, encode_message, _next_id,
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
    assert "id" not in msg


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


def test_encode_message():
    msg = {"jsonrpc": "2.0", "method": "test"}
    encoded = encode_message(msg)
    assert b"Content-Length:" in encoded
    assert b"test" in encoded


def test_atomic_request_id_unique():
    """Request IDs are always unique, even when generated concurrently."""
    ids = []

    def generate_ids(n):
        for _ in range(n):
            ids.append(_next_id())

    threads = [threading.Thread(target=generate_ids, args=(100,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(ids) == 400
    assert len(set(ids)) == 400  # All IDs unique


def test_request_ids_monotonically_increase():
    """Sequential calls produce increasing IDs."""
    id1 = _next_id()
    id2 = _next_id()
    id3 = _next_id()
    assert id1 < id2 < id3


# --- MCP Resources protocol tests ---

def test_create_resources_list_request():
    msg = create_resources_list_request()
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "resources/list"
    assert "id" in msg


def test_create_resources_read_request():
    msg = create_resources_read_request("file:///tmp/test.txt")
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "resources/read"
    assert msg["params"]["uri"] == "file:///tmp/test.txt"
    assert "id" in msg


# --- MCP Prompts protocol tests ---

def test_create_prompts_list_request():
    msg = create_prompts_list_request()
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "prompts/list"
    assert "id" in msg


def test_create_prompts_get_request_without_arguments():
    msg = create_prompts_get_request("my_prompt")
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "prompts/get"
    assert msg["params"]["name"] == "my_prompt"
    assert "arguments" not in msg["params"]
    assert "id" in msg


def test_create_prompts_get_request_with_arguments():
    msg = create_prompts_get_request("my_prompt", {"topic": "AI"})
    assert msg["params"]["name"] == "my_prompt"
    assert msg["params"]["arguments"] == {"topic": "AI"}


# --- MCP Logging protocol tests ---

def test_create_logging_set_level_request():
    msg = create_logging_set_level_request("debug")
    assert msg["jsonrpc"] == "2.0"
    assert msg["method"] == "logging/setLevel"
    assert msg["params"]["level"] == "debug"
    assert "id" in msg


# --- Capability negotiation tests ---

def test_capability_negotiation_includes_all_capabilities():
    msg = create_initialize_request()
    caps = msg["params"]["capabilities"]
    assert "tools" in caps
    assert caps["tools"]["listChanged"] is True
    assert "resources" in caps
    assert caps["resources"]["subscribe"] is False
    assert caps["resources"]["listChanged"] is True
    assert "prompts" in caps
    assert caps["prompts"]["listChanged"] is True
    assert "logging" in caps
