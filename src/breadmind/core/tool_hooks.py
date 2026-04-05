"""Tool pre/post execution hook system."""

from __future__ import annotations

import asyncio
import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


@dataclass
class ToolHookResult:
    """Hook execution result."""

    action: str = "continue"  # "continue" | "block" | "modify"
    modified_input: dict[str, Any] | None = None  # for "modify" action
    additional_context: str = ""  # injected into tool result
    block_reason: str = ""  # for "block" action


class ToolHookType(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"


@dataclass
class ToolHookConfig:
    """Hook configuration."""

    name: str
    hook_type: ToolHookType
    tool_pattern: str  # glob pattern matching tool names (e.g. "shell_*", "*")
    handler: Callable  # sync or async callable
    priority: int = 0  # higher = runs first


class ToolHookRunner:
    """Manages and executes tool hooks."""

    def __init__(self) -> None:
        self._hooks: list[ToolHookConfig] = []

    def register(self, hook: ToolHookConfig) -> None:
        """Register a hook."""
        self._hooks.append(hook)

    def unregister(self, name: str) -> bool:
        """Remove a hook by name. Returns True if found."""
        before = len(self._hooks)
        self._hooks = [h for h in self._hooks if h.name != name]
        return len(self._hooks) < before

    async def run_pre_hooks(
        self, tool_name: str, arguments: dict
    ) -> ToolHookResult:
        """Run all matching pre-hooks in priority order.

        Returns aggregated result: if any hook blocks, result is block.
        If any hook modifies, accumulate modifications.
        """
        matching = self._get_matching_hooks(tool_name, ToolHookType.PRE_TOOL_USE)
        result = ToolHookResult()
        current_args = dict(arguments)

        for hook in matching:
            hook_result = await self._invoke(hook.handler, tool_name, current_args)

            if hook_result.action == "block":
                return ToolHookResult(
                    action="block", block_reason=hook_result.block_reason
                )

            if hook_result.action == "modify" and hook_result.modified_input is not None:
                current_args.update(hook_result.modified_input)
                result.action = "modify"
                result.modified_input = dict(current_args)

            if hook_result.additional_context:
                if result.additional_context:
                    result.additional_context += "\n"
                result.additional_context += hook_result.additional_context

        return result

    async def run_post_hooks(
        self,
        tool_name: str,
        arguments: dict,
        result: str,
        success: bool,
    ) -> ToolHookResult:
        """Run all matching post-hooks. Can inject additional context."""
        matching = self._get_matching_hooks(tool_name, ToolHookType.POST_TOOL_USE)
        aggregated = ToolHookResult()

        for hook in matching:
            hook_result = await self._invoke(
                hook.handler, tool_name, arguments, result, success
            )
            if hook_result.additional_context:
                if aggregated.additional_context:
                    aggregated.additional_context += "\n"
                aggregated.additional_context += hook_result.additional_context

        return aggregated

    def _matches(self, pattern: str, tool_name: str) -> bool:
        """Glob-style matching: '*' matches all, 'shell_*' matches shell_exec etc."""
        return fnmatch.fnmatch(tool_name, pattern)

    def _get_matching_hooks(
        self, tool_name: str, hook_type: ToolHookType
    ) -> list[ToolHookConfig]:
        """Get hooks matching tool name and type, sorted by priority (highest first)."""
        matching = [
            h
            for h in self._hooks
            if h.hook_type == hook_type and self._matches(h.tool_pattern, tool_name)
        ]
        matching.sort(key=lambda h: h.priority, reverse=True)
        return matching

    @staticmethod
    async def _invoke(handler: Callable, *args: Any) -> ToolHookResult:
        """Invoke a handler, supporting both sync and async callables."""
        if asyncio.iscoroutinefunction(handler):
            result = await handler(*args)
        else:
            result = handler(*args)
        if not isinstance(result, ToolHookResult):
            return ToolHookResult()
        return result
