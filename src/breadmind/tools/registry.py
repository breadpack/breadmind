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
            original_name = name.split("__", 1)[1] if "__" in name else name
            return await self._mcp_callback(server_name, original_name, arguments)

        return ToolResult(success=False, output=f"Tool not found: {name}")
