import pytest
import json
import threading
from breadmind.tools.mcp_protocol import (
    create_initialize_request, create_tools_list_request,
    create_tools_call_request, create_initialized_notification,
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
