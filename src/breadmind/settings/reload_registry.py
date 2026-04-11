"""Dispatches SETTINGS_CHANGED events to key-pattern subscribers.

Registering:
    registry.register("llm", reload_llm)
    registry.register("apikey:*", reload_credential)

Dispatching:
    result = await registry.dispatch(
        key="llm", operation="set", old={...}, new={...}
    )

Patterns:
    - Exact key (``"llm"``) matches only that key.
    - Prefix glob (``"apikey:*"``) matches any key starting with ``"apikey:"``.

Reload functions may be sync or async and must accept a single ``ctx`` dict
with fields ``key``, ``operation``, ``old``, ``new``. One failing subscriber
never blocks the others; the exception is captured in ``DispatchResult.errors``.
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ReloadFn = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass
class DispatchResult:
    all_ok: bool
    ran: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class SettingsReloadRegistry:
    def __init__(self) -> None:
        self._subs: list[tuple[str, ReloadFn]] = []

    def register(self, pattern: str, fn: ReloadFn) -> None:
        self._subs.append((pattern, fn))

    def _matches(self, pattern: str, key: str) -> bool:
        if pattern.endswith(":*"):
            return key.startswith(pattern[:-1])
        return pattern == key

    async def dispatch(
        self,
        *,
        key: str,
        operation: str,
        old: Any,
        new: Any,
    ) -> DispatchResult:
        matching = [(p, fn) for p, fn in self._subs if self._matches(p, key)]
        if not matching:
            return DispatchResult(all_ok=True)

        ctx = {"key": key, "operation": operation, "old": old, "new": new}

        async def _run(pattern: str, fn: ReloadFn) -> tuple[str, Exception | None]:
            try:
                if inspect.iscoroutinefunction(fn):
                    await fn(ctx)
                else:
                    await asyncio.to_thread(fn, ctx)
                return pattern, None
            except Exception as exc:  # noqa: BLE001
                return pattern, exc

        results = await asyncio.gather(*(_run(p, fn) for p, fn in matching))

        ran: list[str] = []
        errors: dict[str, str] = {}
        for pattern, exc in results:
            ran.append(pattern)
            if exc is not None:
                errors[pattern] = f"{type(exc).__name__}: {exc}"

        return DispatchResult(all_ok=not errors, ran=ran, errors=errors)
