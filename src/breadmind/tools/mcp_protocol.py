import itertools
import json
from typing import Any

_request_counter = itertools.count(1)


def _next_id() -> int:
    return next(_request_counter)


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
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": True},
                "prompts": {"listChanged": True},
                "logging": {},
            },
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


def create_resources_list_request() -> dict:
    return {"jsonrpc": "2.0", "id": _next_id(), "method": "resources/list"}


def create_resources_read_request(uri: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "resources/read",
        "params": {"uri": uri},
    }


def create_prompts_list_request() -> dict:
    return {"jsonrpc": "2.0", "id": _next_id(), "method": "prompts/list"}


def create_prompts_get_request(name: str, arguments: dict | None = None) -> dict:
    params: dict[str, Any] = {"name": name}
    if arguments:
        params["arguments"] = arguments
    return {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "prompts/get",
        "params": params,
    }


def create_logging_set_level_request(level: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "logging/setLevel",
        "params": {"level": level},
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
