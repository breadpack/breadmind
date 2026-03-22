from __future__ import annotations

import asyncio
import platform

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
