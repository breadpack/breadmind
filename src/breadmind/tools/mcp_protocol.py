import json
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
            "clientInfo": {"name": "breadmind", "version": "0.1.0"},
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
        "params": {"name": name, "arguments": arguments},
    }

def encode_message(msg: dict) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    return header + body

def parse_response(raw: dict) -> Any:
    if "error" in raw:
        err = raw["error"]
        raise MCPError(err.get("code", -1), err.get("message", "Unknown error"))
    return raw.get("result")
