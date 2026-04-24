from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

from breadmind.coding.executors.base import Executor, ExecutionResult


class LocalExecutor(Executor):
    async def run(self, command: list[str], cwd: str, timeout: int = 300) -> ExecutionResult:
        proc = None
        try:
            # Build env: inherit parent but remove ANTHROPIC_API_KEY
            # so Claude Code CLI uses its own local OAuth authentication
            import os
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecutionResult(
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
                returncode=proc.returncode,
            )
        except FileNotFoundError:
            return ExecutionResult(
                stdout="",
                stderr=f"Command not found: {command[0]}",
                returncode=127,
            )
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            return ExecutionResult(
                stdout="",
                stderr=f"Timeout after {timeout}s",
                returncode=-1,
            )

    async def run_phase_async(
        self, phase: dict[str, Any], adapter: Any,
    ) -> asyncio.subprocess.Process:
        """Start phase as async subprocess; caller drains stdout/stderr and waits."""
        cmd = adapter.build_phase_command(phase)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return proc

    async def cancel(
        self, proc: asyncio.subprocess.Process, grace_seconds: float = 2.0,
    ) -> None:
        """Cancel a running subprocess: SIGTERM, wait grace, then SIGKILL.

        On Windows, proc.terminate() maps to TerminateProcess which is
        equivalent to SIGKILL (no graceful termination path).
        """
        if proc.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
            return
        except asyncio.TimeoutError:
            pass
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
