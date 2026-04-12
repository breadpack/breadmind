from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionKind(str, Enum):
    PROCEED = "proceed"
    BLOCK = "block"
    MODIFY = "modify"
    REPLY = "reply"
    REROUTE = "reroute"


@dataclass
class HookDecision:
    kind: DecisionKind = DecisionKind.PROCEED
    reason: str = ""
    patch: dict[str, Any] = field(default_factory=dict)
    reply: Any = None
    reroute_target: str | None = None
    reroute_args: dict[str, Any] | None = None
    context: str = ""
    hook_id: str = ""


def _proceed(cls, context: str = "") -> "HookDecision":
    return cls(kind=DecisionKind.PROCEED, context=context)


def _block(cls, reason: str) -> "HookDecision":
    return cls(kind=DecisionKind.BLOCK, reason=reason)


def _modify(cls, **patch: Any) -> "HookDecision":
    return cls(kind=DecisionKind.MODIFY, patch=dict(patch))


def _reply(cls, result: Any, context: str = "") -> "HookDecision":
    return cls(kind=DecisionKind.REPLY, reply=result, context=context)


def _reroute(cls, target: str, **args: Any) -> "HookDecision":
    return cls(
        kind=DecisionKind.REROUTE,
        reroute_target=target,
        reroute_args=dict(args),
    )


HookDecision.proceed = classmethod(_proceed)  # type: ignore[assignment]
HookDecision.block = classmethod(_block)  # type: ignore[assignment]
HookDecision.modify = classmethod(_modify)  # type: ignore[assignment]
HookDecision.reply = classmethod(_reply)  # type: ignore[assignment]
HookDecision.reroute = classmethod(_reroute)  # type: ignore[assignment]
