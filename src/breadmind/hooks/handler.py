from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import sys
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, runtime_checkable

from breadmind.hooks.decision import DecisionKind, HookDecision
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
    if_condition: str | list[str] | None = None

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


def _parse_shell_decision(stdout: str, event: HookEvent) -> HookDecision:
    stdout = stdout.strip()
    if not stdout:
        return HookDecision.proceed()
    try:
        obj = json.loads(stdout)
    except json.JSONDecodeError:
        return HookDecision.proceed(context=stdout)
    action = obj.get("action", "proceed")
    if action == "block":
        return HookDecision.block(obj.get("reason", "blocked by shell hook"))
    if action == "modify":
        patch = obj.get("patch", {})
        d = HookDecision(kind=DecisionKind.MODIFY, patch=dict(patch))
        if "context" in obj:
            d.context = obj["context"]
        return d
    if action == "reply":
        return HookDecision.reply(obj.get("result"), context=obj.get("context", ""))
    if action == "reroute":
        return HookDecision.reroute(
            obj.get("target", ""),
            **obj.get("args", {}),
        )
    return HookDecision.proceed(context=obj.get("context", ""))


@dataclass
class ShellHook:
    name: str
    event: HookEvent
    command: str
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 10.0
    shell: str = "auto"  # "sh" | "python" | "auto"
    if_condition: str | list[str] | None = None

    def _resolve_executable(self) -> tuple[str, list[str]]:
        choice = self.shell
        if choice == "auto":
            choice = "python" if platform.system() == "Windows" else "sh"
        if choice == "python":
            return sys.executable, ["-c", self.command]
        return "/bin/sh", ["-c", self.command]

    def _build_env(self, payload: HookPayload) -> dict[str, str]:
        env = {**os.environ}
        env["HOOK_EVENT"] = payload.event.value
        env["HOOK_NAME"] = self.name
        data = payload.data or {}
        if "tool_name" in data:
            env["TOOL_NAME"] = str(data["tool_name"])
        if "args" in data:
            env["TOOL_ARGS"] = json.dumps(data["args"], default=str)
        if "result" in data:
            env["TOOL_RESULT"] = str(data["result"])[:32000]
        return env

    async def run(self, payload: HookPayload) -> HookDecision:
        exe, args = self._resolve_executable()
        env = self._build_env(payload)
        stdin_data = json.dumps(
            {"event": payload.event.value, "data": payload.data},
            default=str,
        ).encode("utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                exe, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=self.timeout_sec,
            )
            stdout = stdout_b.decode(errors="replace")
            stderr = stderr_b.decode(errors="replace").strip()

            if proc.returncode != 0:
                reason = stderr or f"exit code {proc.returncode}"
                d = _failure_decision(self.event, reason)
                d.hook_id = self.name
                return d

            decision = _parse_shell_decision(stdout, self.event)
            decision.hook_id = self.name
            return decision

        except asyncio.TimeoutError:
            d = _failure_decision(
                self.event, f"shell hook '{self.name}' timeout",
            )
            d.hook_id = self.name
            return d
        except Exception as e:
            d = _failure_decision(
                self.event, f"shell hook '{self.name}' error: {e}",
            )
            d.hook_id = self.name
            return d
