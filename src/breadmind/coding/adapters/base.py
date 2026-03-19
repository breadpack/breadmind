from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CodingResult:
    success: bool
    output: str
    files_changed: list[str] = field(default_factory=list)
    cost: dict | None = None
    execution_time: float = 0.0
    agent: str = ""
    session_id: str | None = None


class CodingAgentAdapter(ABC):
    name: str = ""
    cli_command: str = ""
    config_filename: str = ""

    @abstractmethod
    def build_command(self, project: str, prompt: str, options: dict | None = None) -> list[str]: ...

    @abstractmethod
    def parse_result(self, stdout: str, stderr: str, returncode: int) -> CodingResult: ...
