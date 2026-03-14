import pytest
import json
from breadmind.tools.mcp_protocol import (
    create_initialize_request, create_tools_list_request,
    create_tools_call_request, create_initialized_notification,
    parse_response, MCPError, encode_message,
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
