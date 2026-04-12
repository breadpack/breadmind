from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, runtime_checkable

from breadmind.hooks.decision import HookDecision
from breadmind.hooks.events import HookEvent, HookPayload, is_blockable

logger = logging.getLogger(__name__)


@runtime_checkable
class HookHandler(Protocol):
    name: str
    event: HookEvent
    priority: int

    async def run(self, payload: HookPayload) -> HookDecision: ...


def _failure_decision(event: HookEvent, reason: str) -> HookDecision:
    if is_blockable(event):
        return HookDecision.block(reason)
    logger.warning("Hook failed on observational event %s: %s", event.value, reason)
    return HookDecision.proceed()


@dataclass
class PythonHook:
    name: str
    event: HookEvent
    handler: Callable[[HookPayload], Awaitable[HookDecision] | HookDecision]
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 5.0

    async def run(self, payload: HookPayload) -> HookDecision:
        try:
            async def _invoke() -> HookDecision:
                result = self.handler(payload)
                if asyncio.iscoroutine(result):
                    result = await result
                if not isinstance(result, HookDecision):
                    return HookDecision.proceed()
                return result

            decision = await asyncio.wait_for(_invoke(), timeout=self.timeout_sec)
            decision.hook_id = self.name
            return decision

        except asyncio.TimeoutError:
            d = _failure_decision(
                self.event,
                f"hook '{self.name}' timeout after {self.timeout_sec}s",
            )
            d.hook_id = self.name
            return d
        except Exception as e:
            d = _failure_decision(self.event, f"hook '{self.name}' error: {e}")
            d.hook_id = self.name
            return d
