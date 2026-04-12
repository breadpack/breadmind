from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from typing import Any

from breadmind.hooks.decision import DecisionKind, HookDecision
from breadmind.hooks.events import (
    HookEvent,
    HookPayload,
    allows_reply,
    allows_reroute,
    is_blockable,
    is_mutable,
)
from breadmind.hooks.condition import matches_condition
from breadmind.hooks.handler import HookHandler

logger = logging.getLogger(__name__)

MAX_REROUTE_DEPTH = 3


@dataclass
class HookChain:
    event: HookEvent
    handlers: list[HookHandler] = field(default_factory=list)

    def _sorted(self) -> list[HookHandler]:
        return sorted(self.handlers, key=lambda h: getattr(h, "priority", 0), reverse=True)

    async def run(
        self, payload: HookPayload,
    ) -> tuple[HookDecision, HookPayload]:
        """Run all handlers in priority order. Mutation updates payload.data.

        Returns (final_decision, possibly_mutated_payload).
        """
        blockable = is_blockable(self.event)
        mutable = is_mutable(self.event)
        reply_ok = allows_reply(self.event)
        reroute_ok = allows_reroute(self.event)

        aggregated_patch: dict[str, Any] = {}
        aggregated_context: list[str] = []

        for handler in self._sorted():
            if_cond = getattr(handler, "if_condition", None)
            if if_cond is not None and not matches_condition(if_cond, payload):
                continue
            t0 = _time.perf_counter()
            decision = await handler.run(payload)
            duration_ms = (_time.perf_counter() - t0) * 1000.0
            try:
                from breadmind.hooks.trace import HookTraceEntry, get_trace_buffer
                get_trace_buffer().record(HookTraceEntry(
                    timestamp=_time.time(),
                    hook_id=getattr(handler, "name", ""),
                    event=self.event.value,
                    decision=decision.kind.value,
                    duration_ms=duration_ms,
                    reason=decision.reason,
                    error="",
                ))
            except Exception:
                pass  # observability must never break the chain

            if decision.context:
                aggregated_context.append(decision.context)

            if decision.kind == DecisionKind.PROCEED:
                continue

            if decision.kind == DecisionKind.BLOCK:
                if blockable:
                    return decision, payload
                logger.warning(
                    "Hook %s returned BLOCK on observational event %s; ignoring",
                    handler.name, self.event.value,
                )
                continue

            if decision.kind == DecisionKind.MODIFY:
                if not mutable:
                    logger.warning(
                        "Hook %s returned MODIFY on non-mutable event %s; ignoring",
                        handler.name, self.event.value,
                    )
                    continue
                aggregated_patch.update(decision.patch)
                payload.data = {**payload.data, **decision.patch}
                continue

            if decision.kind == DecisionKind.REPLY:
                if reply_ok:
                    return decision, payload
                logger.warning(
                    "Hook %s returned REPLY on event %s which does not allow reply; ignoring",
                    handler.name, self.event.value,
                )
                continue

            if decision.kind == DecisionKind.REROUTE:
                if not reroute_ok:
                    logger.warning(
                        "Hook %s returned REROUTE on event %s which does not allow reroute; ignoring",
                        handler.name, self.event.value,
                    )
                    continue
                if payload.depth >= MAX_REROUTE_DEPTH:
                    logger.warning(
                        "Hook %s REROUTE ignored: depth %d >= %d",
                        handler.name, payload.depth, MAX_REROUTE_DEPTH,
                    )
                    continue
                target = decision.reroute_target or ""
                if target in payload.visited:
                    logger.warning(
                        "Hook %s REROUTE ignored: target %r already visited",
                        handler.name, target,
                    )
                    continue
                return decision, payload

        if aggregated_patch:
            final = HookDecision(
                kind=DecisionKind.MODIFY,
                patch=aggregated_patch,
                context="\n".join(aggregated_context),
            )
        else:
            final = HookDecision.proceed(context="\n".join(aggregated_context))
        return final, payload
