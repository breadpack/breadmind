from __future__ import annotations

import asyncio
import shlex

from breadmind.coding.executors.base import Executor, ExecutionResult


class RemoteExecutor(Executor):
    def __init__(self, host: str, username: str, password: str | None = None):
        self.host = host
        self.username = username
        self.password = password

    async def run(self, command: list[str], cwd: str, timeout: int = 300) -> ExecutionResult:
        import asyncssh

        safe_cwd = shlex.quote(cwd)
        full_cmd = f"cd {safe_cwd} && {' '.join(shlex.quote(c) for c in command)}"

        password = self.password
        if password and password.startswith("credential_ref:"):
            from breadmind.storage.credential_vault import CredentialVault
            vault = CredentialVault()
            password = vault.resolve(password)

        try:
            async with asyncssh.connect(
                self.host,
                username=self.username,
                password=password,
                known_hosts=None,
            ) as conn:
                result = await asyncio.wait_for(
                    conn.run(full_cmd),
                    timeout=timeout,
                )
                return ExecutionResult(
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                    returncode=result.returncode or 0,
                )
        except asyncio.TimeoutError:
            return ExecutionResult(
                stdout="",
                stderr=f"Timeout after {timeout}s",
                returncode=-1,
            )
        except Exception as exc:
            return ExecutionResult(
                stdout="",
                stderr=str(exc),
                returncode=-1,
            )
