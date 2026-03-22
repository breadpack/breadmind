import inspect
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from breadmind.llm.base import ToolDefinition

MAX_OUTPUT_SIZE: int = 50_000


@dataclass
class ToolResult:
    success: bool
    output: str
    not_found: bool = False


def tool(description: str):
    """Decorator to register a function as an agent tool."""
    def decorator(func: Callable):
        sig = inspect.signature(func)
        properties = {}
        required = []
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            prop = {"type": "string"}
            annotation = param.annotation
            if annotation is int:
                prop = {"type": "integer"}
            elif annotation is float:
                prop = {"type": "number"}
            elif annotation is bool:
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


def _validate_and_coerce_arguments(
    func: Callable,
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Validate arguments against the tool's schema and coerce types.

    - Filters out unexpected parameters not in the function signature.
    - Coerces types based on the JSON schema (e.g., string "123" -> int 123).
    - Raises ValueError on validation failure.
    """
    sig = inspect.signature(func)
    valid_params = set(sig.parameters.keys())
    properties = schema.get("properties", {})

    # Filter out unexpected parameters
    filtered = {}
    for key, value in arguments.items():
        if key not in valid_params:
            continue
        # Type coercion based on schema
        prop_schema = properties.get(key, {})
        expected_type = prop_schema.get("type")
        if expected_type and value is not None:
            try:
                value = _coerce_type(value, expected_type)
            except (ValueError, TypeError) as e:
                raise ValueError(
                    f"Parameter '{key}': cannot convert {type(value).__name__} "
                    f"to {expected_type}: {e}"
                )
        filtered[key] = value

    return filtered


def _coerce_type(value: Any, expected_type: str) -> Any:
    """Coerce a value to match the expected JSON schema type."""
    if expected_type == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            return int(value)
        if isinstance(value, float):
            return int(value)
        raise TypeError(f"Cannot convert {type(value).__name__} to integer")
    elif expected_type == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            return float(value)
        raise TypeError(f"Cannot convert {type(value).__name__} to number")
    elif expected_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                return True
            if value.lower() in ("false", "0", "no"):
                return False
        raise TypeError(f"Cannot convert {type(value).__name__} to boolean")
    elif expected_type == "string":
        if isinstance(value, str):
            return value
        return str(value)
    return value


def _truncate_output(output: str) -> str:
    """Truncate output if it exceeds MAX_OUTPUT_SIZE."""
    if len(output) > MAX_OUTPUT_SIZE:
        return output[:MAX_OUTPUT_SIZE] + f"[...truncated, showing first {MAX_OUTPUT_SIZE} chars]"
    return output


class ToolResultCache:
    """TTL-based cache for tool results."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        self._cache: dict[str, tuple[float, ToolResult]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size

    def get(self, tool_name: str, arguments: dict) -> ToolResult | None:
        key = self._make_key(tool_name, arguments)
        if key in self._cache:
            ts, result = self._cache[key]
            if time.monotonic() - ts < self._ttl:
                return result
            del self._cache[key]
        return None

    def set(self, tool_name: str, arguments: dict, result: ToolResult):
        if len(self._cache) >= self._max_size:
            # Evict oldest entry
            oldest_key = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest_key]
        key = self._make_key(tool_name, arguments)
        self._cache[key] = (time.monotonic(), result)

    def _make_key(self, tool_name: str, arguments: dict) -> str:
        return hashlib.sha256(
            json.dumps({"t": tool_name, "a": arguments}, sort_keys=True).encode()
        ).hexdigest()


class ToolRegistry:
    def __init__(self, cache: ToolResultCache | None = None,
                 cacheable_tools: set[str] | None = None):
        self._tools: dict[str, Callable] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._mcp_tools: dict[str, str] = {}  # tool_name -> server_name
        self._mcp_callback: Callable | None = None
        self.cache = cache
        self.cacheable_tools: set[str] = cacheable_tools or set()

    def register(self, func: Callable):
        defn = getattr(func, "_tool_definition", None)
        if defn is None:
            raise ValueError(f"{func.__name__} is not decorated with @tool")
        self._tools[defn.name] = func
        self._definitions[defn.name] = defn

    def unregister(self, name: str) -> bool:
        """Remove a builtin tool by name. Returns True if found."""
        removed = self._tools.pop(name, None) is not None
        self._definitions.pop(name, None)
        return removed

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
        # Check cache for cacheable tools
        if self.cache and name in self.cacheable_tools:
            cached = self.cache.get(name, arguments)
            if cached is not None:
                return cached

        # Check builtin first
        func = self._tools.get(name)
        if func is not None:
            defn = self._definitions.get(name)
            try:
                # Validate and coerce arguments
                if defn:
                    arguments = _validate_and_coerce_arguments(
                        func, arguments, defn.parameters
                    )
                else:
                    # Fallback: filter by signature only
                    sig = inspect.signature(func)
                    valid_params = set(sig.parameters.keys())
                    arguments = {k: v for k, v in arguments.items() if k in valid_params}

                if asyncio.iscoroutinefunction(func):
                    output = await func(**arguments)
                else:
                    output = func(**arguments)
                output_str = _truncate_output(str(output))
                result = ToolResult(success=True, output=output_str)

                # Cache successful result if cacheable
                if self.cache and name in self.cacheable_tools and result.success:
                    self.cache.set(name, arguments, result)

                return result
            except ValueError as e:
                return ToolResult(success=False, output=f"Validation error: {e}")
            except Exception as e:
                return ToolResult(success=False, output=f"Tool error: {e}")

        # Check MCP tool
        server_name = self._mcp_tools.get(name)
        if server_name is not None and self._mcp_callback:
            original_name = name.split("__", 1)[1] if "__" in name else name
            result = await self._mcp_callback(server_name, original_name, arguments)

            # Cache successful MCP result if cacheable
            if self.cache and name in self.cacheable_tools and result.success:
                self.cache.set(name, arguments, result)

            return result

        return ToolResult(success=False, output=f"Tool not found: {name}", not_found=True)
