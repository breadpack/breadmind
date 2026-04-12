from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(str, Enum):
    # Claude Code compat
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
    NOTIFICATION = "notification"
    PRE_COMPACT = "pre_compact"
    # BreadMind native
    MESSENGER_RECEIVED = "messenger_received"
    MESSENGER_SENDING = "messenger_sending"
    SAFETY_GUARD_TRIGGERED = "safety_guard_triggered"
    WORKER_DISPATCHED = "worker_dispatched"
    WORKER_COMPLETED = "worker_completed"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    MEMORY_WRITTEN = "memory_written"
    PLUGIN_LOADED = "plugin_loaded"
    PLUGIN_UNLOADED = "plugin_unloaded"
    CREDENTIAL_ACCESSED = "credential_accessed"


@dataclass(frozen=True)
class EventPolicy:
    blockable: bool = False
    mutable: bool = False
    reply_allowed: bool = False
    reroute_allowed: bool = False


EVENT_POLICY: dict[HookEvent, EventPolicy] = {
    HookEvent.SESSION_START: EventPolicy(),
    HookEvent.SESSION_END: EventPolicy(),
    HookEvent.USER_PROMPT_SUBMIT: EventPolicy(True, True, True, True),
    HookEvent.PRE_TOOL_USE: EventPolicy(True, True, True, True),
    HookEvent.POST_TOOL_USE: EventPolicy(False, True, False, False),
    HookEvent.STOP: EventPolicy(),
    HookEvent.SUBAGENT_STOP: EventPolicy(),
    HookEvent.NOTIFICATION: EventPolicy(),
    HookEvent.PRE_COMPACT: EventPolicy(True, True, False, False),
    HookEvent.MESSENGER_RECEIVED: EventPolicy(True, True, True, True),
    HookEvent.MESSENGER_SENDING: EventPolicy(True, True, False, False),
    HookEvent.SAFETY_GUARD_TRIGGERED: EventPolicy(True, True, True, False),
    HookEvent.WORKER_DISPATCHED: EventPolicy(),
    HookEvent.WORKER_COMPLETED: EventPolicy(),
    HookEvent.LLM_REQUEST: EventPolicy(True, True, True, False),
    HookEvent.LLM_RESPONSE: EventPolicy(False, True, False, False),
    HookEvent.MEMORY_WRITTEN: EventPolicy(),
    HookEvent.PLUGIN_LOADED: EventPolicy(),
    HookEvent.PLUGIN_UNLOADED: EventPolicy(),
    HookEvent.CREDENTIAL_ACCESSED: EventPolicy(),
}


def _policy(event: HookEvent | str) -> EventPolicy:
    key = HookEvent(event) if isinstance(event, str) else event
    return EVENT_POLICY.get(key, EventPolicy())


def is_blockable(event: HookEvent | str) -> bool:
    return _policy(event).blockable


def is_mutable(event: HookEvent | str) -> bool:
    return _policy(event).mutable


def allows_reply(event: HookEvent | str) -> bool:
    return _policy(event).reply_allowed


def allows_reroute(event: HookEvent | str) -> bool:
    return _policy(event).reroute_allowed


@dataclass
class HookPayload:
    event: HookEvent
    data: dict[str, Any] = field(default_factory=dict)
    depth: int = 0
    visited: set[str] = field(default_factory=set)
    session_id: str = ""
    trace_id: str = ""
