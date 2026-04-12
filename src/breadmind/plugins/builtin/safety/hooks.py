"""Pre/Post tool-use hook system for BreadMind."""
from __future__ import annotations

import asyncio
import json
import logging
import platform
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HookDefinition:
    """Hook 정의."""
    event: str  # "pre_tool_use" | "post_tool_use"
    tool_pattern: str  # glob pattern (e.g., "shell_*", "*", "k8s_*")
    command: str  # shell command to execute
    timeout: int = 10  # seconds


@dataclass
class HookResult:
    """Hook 실행 결과."""
    passed: bool
    output: str = ""
    error: str | None = None


class HookRunner:
    """Pre/Post tool-use hook runner."""

    def __init__(self) -> None:
        self._hooks: list[HookDefinition] = []

    def register(self, hook: HookDefinition) -> None:
        """Hook 등록."""
        self._hooks.append(hook)

    def unregister(self, event: str, tool_pattern: str) -> None:
        """이벤트와 패턴이 일치하는 hook 제거."""
        self._hooks = [
            h for h in self._hooks
            if not (h.event == event and h.tool_pattern == tool_pattern)
        ]

    def _matching_hooks(self, event: str, tool_name: str) -> list[HookDefinition]:
        """이벤트와 tool 이름에 매칭되는 hook 목록 반환."""
        return [
            h for h in self._hooks
            if h.event == event and fnmatch(tool_name, h.tool_pattern)
        ]

    async def _execute_hook(
        self, hook: HookDefinition, env: dict[str, str],
    ) -> HookResult:
        """단일 hook command를 실행."""
        try:
            if platform.system() == "Windows":
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-c", hook.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "/bin/sh", "-c", hook.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=hook.timeout,
            )
            output = stdout.decode(errors="replace").strip()
            err_output = stderr.decode(errors="replace").strip()

            if proc.returncode != 0:
                return HookResult(
                    passed=False,
                    output=output,
                    error=err_output or f"exit code {proc.returncode}",
                )
            return HookResult(passed=True, output=output)

        except asyncio.TimeoutError:
            return HookResult(
                passed=False, output="", error=f"Hook timed out after {hook.timeout}s",
            )
        except Exception as e:
            return HookResult(passed=False, output="", error=str(e))

    def _build_env(
        self, tool_name: str, arguments: dict[str, Any],
        result: str | None = None,
    ) -> dict[str, str]:
        """Hook command에 전달할 환경변수 빌드."""
        import os
        env = {**os.environ}
        env["TOOL_NAME"] = tool_name
        env["TOOL_ARGS"] = json.dumps(arguments, default=str)
        if result is not None:
            env["TOOL_RESULT"] = result
        return env

    async def run_pre_tool_use(
        self, tool_name: str, arguments: dict[str, Any],
    ) -> HookResult:
        from breadmind.hooks.chain import HookChain
        from breadmind.hooks.events import HookEvent, HookPayload
        from breadmind.hooks.handler import ShellHook

        hooks = self._matching_hooks("pre_tool_use", tool_name)
        if not hooks:
            return HookResult(passed=True)

        handlers = [
            ShellHook(
                name=f"safety-pre-{i}",
                event=HookEvent.PRE_TOOL_USE,
                command=h.command,
                timeout_sec=float(h.timeout),
                tool_pattern=h.tool_pattern,
            )
            for i, h in enumerate(hooks)
        ]
        chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=handlers)
        payload = HookPayload(
            event=HookEvent.PRE_TOOL_USE,
            data={"tool_name": tool_name, "args": dict(arguments)},
        )
        decision, _ = await chain.run(payload)
        if decision.kind.value == "block":
            return HookResult(passed=False, error=decision.reason)
        return HookResult(passed=True, output=decision.context)

    async def run_post_tool_use(
        self, tool_name: str, arguments: dict[str, Any], result: str,
    ) -> HookResult:
        from breadmind.hooks.chain import HookChain
        from breadmind.hooks.events import HookEvent, HookPayload
        from breadmind.hooks.handler import ShellHook

        hooks = self._matching_hooks("post_tool_use", tool_name)
        if not hooks:
            return HookResult(passed=True)

        handlers = [
            ShellHook(
                name=f"safety-post-{i}",
                event=HookEvent.POST_TOOL_USE,
                command=h.command,
                timeout_sec=float(h.timeout),
                tool_pattern=h.tool_pattern,
            )
            for i, h in enumerate(hooks)
        ]
        chain = HookChain(event=HookEvent.POST_TOOL_USE, handlers=handlers)
        payload = HookPayload(
            event=HookEvent.POST_TOOL_USE,
            data={"tool_name": tool_name, "args": dict(arguments), "result": result},
        )
        decision, _ = await chain.run(payload)
        return HookResult(passed=True, output=decision.context)
