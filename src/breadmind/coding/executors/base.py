from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int


class Executor(ABC):
    @abstractmethod
    async def run(self, command: list[str], cwd: str, timeout: int = 300) -> ExecutionResult: ...
