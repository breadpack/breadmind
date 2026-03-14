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

    def register(self, func: Callable):
        defn = getattr(func, "_tool_definition", None)
        if defn is None:
            raise ValueError(f"{func.__name__} is not decorated with @tool")
        self._tools[defn.name] = func
        self._definitions[defn.name] = defn

    def get_all_definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        func = self._tools.get(name)
        if func is None:
            return ToolResult(success=False, output=f"Tool not found: {name}")
        try:
            if asyncio.iscoroutinefunction(func):
                output = await func(**arguments)
            else:
                output = func(**arguments)
            return ToolResult(success=True, output=str(output))
        except Exception as e:
            return ToolResult(success=False, output=f"Tool error: {e}")
