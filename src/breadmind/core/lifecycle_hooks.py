"""Extended lifecycle hook types beyond tool pre/post."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class LifecycleEvent(str, Enum):
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
    PRE_COMPACT = "pre_compact"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PERMISSION_REQUEST = "permission_request"
    SESSION_START = "session_start"
    SESSION_END = "session_end"


@dataclass
class LifecycleHookResult:
    allow: bool = True
    modified_input: str | None = None  # for USER_PROMPT_SUBMIT
    permission_decision: str | None = None  # "allow"/"deny"/"ask" for PERMISSION_REQUEST
    additional_context: str = ""


class LifecycleHookRunner:
    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = {}

    def on(self, event: LifecycleEvent, handler: Callable) -> None:
        self._hooks.setdefault(event.value, []).append(handler)

    def off(self, event: LifecycleEvent, handler: Callable) -> None:
        handlers = self._hooks.get(event.value, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event: LifecycleEvent,
                   data: dict[str, Any] | None = None) -> LifecycleHookResult:
        result = LifecycleHookResult()
        for handler in self._hooks.get(event.value, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    hr = await handler(data or {})
                else:
                    hr = handler(data or {})
                if isinstance(hr, LifecycleHookResult):
                    if not hr.allow:
                        result.allow = False
                    if hr.modified_input is not None:
                        result.modified_input = hr.modified_input
                    if hr.permission_decision is not None:
                        result.permission_decision = hr.permission_decision
                    if hr.additional_context:
                        result.additional_context += hr.additional_context
            except Exception as e:
                logger.error("Lifecycle hook error for %s: %s", event.value, e)
        return result
