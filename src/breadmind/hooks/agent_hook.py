"""AgentHook — multi-turn LLM verifier hook handler."""
from __future__ import annotations

import json
import logging
import re
import asyncio
from dataclasses import dataclass
from typing import Any

from breadmind.hooks.decision import HookDecision
from breadmind.hooks.events import HookEvent, HookPayload, is_blockable
from breadmind.hooks.handler import _failure_decision

logger = logging.getLogger(__name__)

READONLY_TOOLS: list[str] = ["Read", "Grep", "Glob"]

_SYSTEM_PROMPT = (
    "You are a hook verifier. Check conditions using tools. "
    "Respond with JSON in the format: {\"ok\": true/false, \"reason\": \"<explanation>\"}."
)


@dataclass
class AgentHook:
    name: str
    event: HookEvent
    prompt: str
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 30.0
    max_turns: int = 3
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] | str = "readonly"
    if_condition: str | list[str] | None = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def _resolve_allowed_tools(self) -> list[str] | None:
        """Return the tool list for this hook.

        - ``"readonly"``       → READONLY_TOOLS
        - ``"all"``            → None  (no filter)
        - explicit list        → that list
        """
        if self.allowed_tools == "readonly":
            return READONLY_TOOLS
        if self.allowed_tools == "all":
            return None
        return list(self.allowed_tools)  # explicit list

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Parse JSON from a free-form LLM response.

        Handles plain JSON objects and ```json ... ``` fenced blocks.
        Returns an empty dict when no valid JSON object is found.
        """
        # 1. Try fenced ```json … ``` block first.
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

        # 2. Try to find the first {...} substring.
        brace = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if brace:
            try:
                return json.loads(brace.group(0))
            except json.JSONDecodeError:
                pass

        return {}

    async def _run_agent_loop(
        self,
        user_prompt: str,
        payload: HookPayload,
    ) -> dict[str, Any]:
        """Run a mini agent loop: prompt → LLM → (tool calls →) response.

        Returns a dict with at least ``ok`` and ``reason`` keys when a valid
        JSON decision is obtained, or an empty dict when max_turns is
        exhausted without a parseable response.

        This method is intentionally thin so tests can mock it directly.
        """
        allowed = self._resolve_allowed_tools()

        # Build the conversation context for the mini-agent.
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{user_prompt}\n\n"
                    f"Hook event: {payload.event.value}\n"
                    f"Payload data: {json.dumps(payload.data, default=str)}"
                ),
            },
        ]

        try:
            from breadmind.llm.factory import create_provider
            from breadmind.tools.registry import ToolRegistry
        except ImportError:
            logger.warning("AgentHook: required modules not available; proceeding.")
            return {}

        # Resolve LLM provider
        provider_name = self.provider
        model_name = self.model
        try:
            llm = await create_provider(provider=provider_name, model=model_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentHook '%s': could not create LLM provider: %s", self.name, exc)
            return {}

        # Resolve tools
        registry = ToolRegistry.get_instance() if hasattr(ToolRegistry, "get_instance") else None
        if registry is not None:
            if allowed is not None:
                tools = [t for t in registry.list_tools() if t.name in allowed]
            else:
                tools = registry.list_tools()
        else:
            tools = []

        # Mini agent loop
        for _turn in range(self.max_turns):
            try:
                response = await llm.chat(messages=messages, tools=tools or None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AgentHook '%s' turn %d error: %s", self.name, _turn, exc)
                break

            # Check for tool calls first
            tool_calls = getattr(response, "tool_calls", None) or []
            assistant_content = getattr(response, "content", "") or ""

            # Append assistant message
            messages.append({"role": "assistant", "content": assistant_content})

            if tool_calls and registry is not None:
                # Execute tool calls and append results
                tool_results: list[dict[str, Any]] = []
                for tc in tool_calls:
                    tool_name = getattr(tc, "name", None) or tc.get("name", "")
                    tool_args = getattr(tc, "args", None) or tc.get("args", {})
                    tool_id = getattr(tc, "id", None) or tc.get("id", "")

                    # Enforce allowed tools
                    if allowed is not None and tool_name not in allowed:
                        tool_results.append({
                            "tool_use_id": tool_id,
                            "content": f"Tool '{tool_name}' is not allowed.",
                        })
                        continue

                    try:
                        result = await registry.execute(tool_name, tool_args)
                        tool_results.append({"tool_use_id": tool_id, "content": str(result)})
                    except Exception as exc:  # noqa: BLE001
                        tool_results.append({
                            "tool_use_id": tool_id,
                            "content": f"Error: {exc}",
                        })
                messages.append({"role": "tool", "content": tool_results})
                continue  # next turn with tool results

            # No tool calls — try to extract JSON decision
            parsed = self._extract_json(assistant_content)
            if "ok" in parsed:
                return parsed

        # max_turns exhausted without a clear answer
        return {}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, payload: HookPayload) -> HookDecision:
        """Execute the agent hook and return a HookDecision."""
        try:
            result = await asyncio.wait_for(
                self._run_agent_loop(self.prompt, payload),
                timeout=self.timeout_sec,
            )
        except asyncio.TimeoutError:
            d = _failure_decision(
                self.event,
                f"agent hook '{self.name}' timeout after {self.timeout_sec}s",
            )
            d.hook_id = self.name
            return d
        except Exception as exc:  # noqa: BLE001
            d = _failure_decision(self.event, f"agent hook '{self.name}' error: {exc}")
            d.hook_id = self.name
            return d

        # Empty dict → turns exhausted without JSON → proceed with warning
        if not result or "ok" not in result:
            logger.warning(
                "AgentHook '%s': turns exhausted without JSON decision; proceeding.",
                self.name,
            )
            d = HookDecision.proceed(context="turns exhausted without decision")
            d.hook_id = self.name
            return d

        ok: bool = bool(result.get("ok", True))
        reason: str = str(result.get("reason", ""))

        if ok:
            d = HookDecision.proceed(context=reason)
        else:
            if is_blockable(self.event):
                d = HookDecision.block(reason or "agent hook rejected")
            else:
                logger.warning(
                    "AgentHook '%s': ok=False on non-blockable event %s; proceeding.",
                    self.name,
                    self.event.value,
                )
                d = HookDecision.proceed(context=reason)

        d.hook_id = self.name
        return d
