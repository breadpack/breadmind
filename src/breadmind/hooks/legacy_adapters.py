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


def _lifecycle_to_hook_event(ev) -> HookEvent | None:
    from breadmind.core.lifecycle_hooks import LifecycleEvent
    mapping = {
        LifecycleEvent.STOP: HookEvent.STOP,
        LifecycleEvent.SUBAGENT_STOP: HookEvent.SUBAGENT_STOP,
        LifecycleEvent.PRE_COMPACT: HookEvent.PRE_COMPACT,
        LifecycleEvent.USER_PROMPT_SUBMIT: HookEvent.USER_PROMPT_SUBMIT,
        LifecycleEvent.PERMISSION_REQUEST: HookEvent.NOTIFICATION,
        LifecycleEvent.SESSION_START: HookEvent.SESSION_START,
        LifecycleEvent.SESSION_END: HookEvent.SESSION_END,
    }
    return mapping.get(ev)


async def run_legacy_lifecycle_chain(handlers, lifecycle_event, data):
    """Run legacy LifecycleHookRunner handlers through the new HookChain.

    Preserves legacy quirks:
    - Denial is sticky across observational events (aggregated outside chain).
    - permission_decision (non-blockable/non-mutable) piggybacks via side
      channel since the chain drops MODIFY patches for non-mutable events.
    - Handler exceptions are swallowed (do not propagate, do not BLOCK).
    """
    from breadmind.core.lifecycle_hooks import LifecycleHookResult

    hook_event = _lifecycle_to_hook_event(lifecycle_event)
    if hook_event is None:
        return LifecycleHookResult()

    sidecar: dict[str, Any] = {
        "permission_decision": None,
        "denied": False,
    }

    py_hooks: list[PythonHook] = []
    for idx, fn in enumerate(handlers):
        def _make(fn=fn):
            async def _wrap(payload):
                try:
                    result = fn(payload.data)
                    if _a.iscoroutine(result):
                        result = await result
                except Exception as e:
                    logger.error(
                        "Lifecycle hook error for %s: %s",
                        payload.event.value, e,
                    )
                    return HookDecision.proceed()

                if not isinstance(result, LifecycleHookResult):
                    return HookDecision.proceed()

                if not result.allow:
                    sidecar["denied"] = True
                if result.permission_decision is not None:
                    sidecar["permission_decision"] = result.permission_decision

                ctx = result.additional_context or ""

                if result.modified_input is not None:
                    d = HookDecision(
                        kind=DecisionKind.MODIFY,
                        patch={"__lifecycle_modified_input__": result.modified_input},
                    )
                    d.context = ctx
                    return d

                if not result.allow:
                    # For blockable events, short-circuit like the new chain.
                    # For observational events, chain ignores BLOCK but we
                    # already recorded it in the sidecar for aggregation.
                    return HookDecision.block("lifecycle denied")

                return HookDecision.proceed(context=ctx)
            return _wrap

        py_hooks.append(PythonHook(
            name=f"legacy-lifecycle-{idx}",
            event=hook_event,
            handler=_make(),
        ))

    chain = HookChain(event=hook_event, handlers=py_hooks)
    payload = HookPayload(event=hook_event, data=dict(data or {}))
    decision, _final = await chain.run(payload)

    out = LifecycleHookResult()
    out.additional_context = decision.context or ""

    if sidecar["denied"] or decision.kind == DecisionKind.BLOCK:
        out.allow = False

    if decision.kind == DecisionKind.MODIFY:
        mi = decision.patch.get("__lifecycle_modified_input__")
        if mi is not None:
            out.modified_input = mi

    if sidecar["permission_decision"] is not None:
        out.permission_decision = sidecar["permission_decision"]

    return out
