from __future__ import annotations

import asyncio as _a
import fnmatch
import logging
from typing import Any

from breadmind.hooks.chain import HookChain
from breadmind.hooks.decision import DecisionKind, HookDecision
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.handler import PythonHook

logger = logging.getLogger(__name__)


def tool_hook_config_to_python_hook(cfg, event: HookEvent) -> PythonHook:
    """Wrap a legacy ToolHookConfig.handler to return HookDecision."""

    async def _wrapped(payload: HookPayload) -> HookDecision:
        from breadmind.core.tool_hooks import (
            HookHandlerType,
            ToolHookResult,
            ToolHookRunner,
        )

        tool_name = payload.data.get("tool_name", "")
        args = payload.data.get("args", {})
        if cfg.tool_pattern and not fnmatch.fnmatch(tool_name, cfg.tool_pattern):
            return HookDecision.proceed()

        legacy_args = [tool_name, args]
        if event == HookEvent.POST_TOOL_USE:
            legacy_args.extend([
                payload.data.get("result", ""),
                payload.data.get("success", True),
            ])

        if cfg.handler_type != HookHandlerType.COMMAND:
            # Preserve legacy PROMPT/AGENT dispatch semantics
            result = await ToolHookRunner._invoke_hook(cfg, *legacy_args)
            if not isinstance(result, ToolHookResult):
                return HookDecision.proceed()
            if result.action == "block":
                return HookDecision.block(result.block_reason)
            if result.action == "modify" and result.modified_input is not None:
                d = HookDecision(kind=DecisionKind.MODIFY, patch={
                    "args": {**args, **result.modified_input},
                })
                if result.additional_context:
                    d.context = result.additional_context
                return d
            if result.additional_context:
                return HookDecision.proceed(context=result.additional_context)
            return HookDecision.proceed()

        result = cfg.handler(*legacy_args)
        if _a.iscoroutine(result):
            result = await result
        if not isinstance(result, ToolHookResult):
            return HookDecision.proceed()

        if result.action == "block":
            return HookDecision.block(result.block_reason)
        if result.action == "modify" and result.modified_input is not None:
            d = HookDecision(kind=DecisionKind.MODIFY, patch={
                "args": {**args, **result.modified_input},
            })
            if result.additional_context:
                d.context = result.additional_context
            return d
        if result.additional_context:
            return HookDecision.proceed(context=result.additional_context)
        return HookDecision.proceed()

    return PythonHook(
        name=cfg.name,
        event=event,
        handler=_wrapped,
        priority=cfg.priority,
        tool_pattern=cfg.tool_pattern,
    )


async def run_legacy_pre_chain(configs, tool_name: str, args: dict[str, Any]):
    from breadmind.core.tool_hooks import ToolHookResult

    event = HookEvent.PRE_TOOL_USE
    handlers = [tool_hook_config_to_python_hook(c, event) for c in configs]
    chain = HookChain(event=event, handlers=handlers)
    payload = HookPayload(
        event=event,
        data={"tool_name": tool_name, "args": dict(args)},
    )
    decision, final_payload = await chain.run(payload)

    if decision.kind == DecisionKind.BLOCK:
        return ToolHookResult(action="block", block_reason=decision.reason)
    if decision.kind == DecisionKind.MODIFY:
        new_args = decision.patch.get("args", final_payload.data.get("args", args))
        return ToolHookResult(
            action="modify",
            modified_input=dict(new_args),
            additional_context=decision.context,
        )
    return ToolHookResult(
        action="continue",
        additional_context=decision.context,
    )


async def run_legacy_post_chain(
    configs,
    tool_name: str,
    args: dict[str, Any],
    result: str,
    success: bool,
):
    from breadmind.core.tool_hooks import ToolHookResult

    event = HookEvent.POST_TOOL_USE
    handlers = [tool_hook_config_to_python_hook(c, event) for c in configs]
    chain = HookChain(event=event, handlers=handlers)
    payload = HookPayload(
        event=event,
        data={
            "tool_name": tool_name,
            "args": dict(args),
            "result": result,
            "success": success,
        },
    )
    decision, _ = await chain.run(payload)
    return ToolHookResult(
        action="continue",
        additional_context=decision.context,
    )
