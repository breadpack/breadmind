"""Tool pre/post execution hook system."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


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


class HookHandlerType(str, Enum):
    """How the hook handler is executed."""

    COMMAND = "command"    # default: invoke a callable directly
    PROMPT = "prompt"      # call an LLM with prompt_template, returns allow/deny
    AGENT = "agent"        # spawn a lightweight check that can read files


@dataclass
class ToolHookConfig:
    """Hook configuration."""

    name: str
    hook_type: ToolHookType
    tool_pattern: str  # glob pattern matching tool names (e.g. "shell_*", "*")
    handler: Callable  # sync or async callable
    priority: int = 0  # higher = runs first
    handler_type: HookHandlerType = HookHandlerType.COMMAND
    # For PROMPT type: Jinja-like template with $ARGUMENTS substitution
    prompt_template: str = ""
    # For PROMPT type: LLM provider callable (async (messages) -> response text)
    llm_provider: Callable | None = None
    # For AGENT type: file reader callback (async (path) -> content)
    file_reader: Callable | None = None


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
        """Run all matching pre-hooks via the new HookChain."""
        from breadmind.hooks.legacy_adapters import run_legacy_pre_chain
        configs = self._get_matching_hooks(tool_name, ToolHookType.PRE_TOOL_USE)
        if not configs:
            return ToolHookResult()
        return await run_legacy_pre_chain(configs, tool_name, arguments)

    async def run_post_hooks(
        self,
        tool_name: str,
        arguments: dict,
        result: str,
        success: bool,
    ) -> ToolHookResult:
        """Run all matching post-hooks via the new HookChain."""
        from breadmind.hooks.legacy_adapters import run_legacy_post_chain
        configs = self._get_matching_hooks(tool_name, ToolHookType.POST_TOOL_USE)
        if not configs:
            return ToolHookResult()
        return await run_legacy_post_chain(
            configs, tool_name, arguments, result, success,
        )

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

    async def _invoke_hook(self, hook: ToolHookConfig, *args: Any) -> ToolHookResult:
        """Dispatch hook execution based on handler_type."""
        if hook.handler_type == HookHandlerType.PROMPT:
            return await self._invoke_prompt_hook(hook, *args)
        elif hook.handler_type == HookHandlerType.AGENT:
            return await self._invoke_agent_hook(hook, *args)
        # Default: COMMAND
        return await self._invoke(hook.handler, *args)

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

    @staticmethod
    async def _invoke_prompt_hook(hook: ToolHookConfig, *args: Any) -> ToolHookResult:
        """PROMPT type: render template with arguments, call LLM, parse allow/deny."""
        if not hook.llm_provider:
            logger.warning("Prompt hook '%s' has no llm_provider, skipping", hook.name)
            return ToolHookResult()

        # Build the prompt by substituting $ARGUMENTS
        import json as _json
        arguments_str = _json.dumps(args[1]) if len(args) > 1 else "{}"
        prompt_text = hook.prompt_template.replace("$ARGUMENTS", arguments_str)

        try:
            if asyncio.iscoroutinefunction(hook.llm_provider):
                response = await hook.llm_provider(prompt_text)
            else:
                response = hook.llm_provider(prompt_text)

            response_lower = response.strip().lower() if isinstance(response, str) else ""
            if response_lower.startswith("deny") or response_lower.startswith("block"):
                return ToolHookResult(
                    action="block",
                    block_reason=f"LLM hook '{hook.name}' denied: {response.strip()}",
                )
            return ToolHookResult(
                action="continue",
                additional_context=response.strip() if isinstance(response, str) else "",
            )
        except Exception as e:
            logger.error("Prompt hook '%s' failed: %s", hook.name, e)
            return ToolHookResult()

    @staticmethod
    async def _invoke_agent_hook(hook: ToolHookConfig, *args: Any) -> ToolHookResult:
        """AGENT type: run handler with file_reader callback, return structured result."""
        try:
            if asyncio.iscoroutinefunction(hook.handler):
                result = await hook.handler(*args, file_reader=hook.file_reader)
            else:
                result = hook.handler(*args, file_reader=hook.file_reader)
            if not isinstance(result, ToolHookResult):
                return ToolHookResult()
            return result
        except Exception as e:
            logger.error("Agent hook '%s' failed: %s", hook.name, e)
            return ToolHookResult()
