"""Shared contracts for every smoke check."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from breadmind.smoke.targets import PilotTargets


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class CheckOutcome:
    name: str
    status: CheckStatus
    detail: str = ""
    duration_ms: int = 0

    @property
    def is_failing(self) -> bool:
        return self.status is CheckStatus.FAIL


class SmokeCheck(Protocol):
    """Every smoke check implements this contract.

    ``depends_on`` is a list of check names that must PASS before this
    check runs; if any dependency FAILs or SKIPs, the runner yields
    ``CheckStatus.SKIP`` with detail ``"dependency <name> not pass"``.
    """

    name: str
    depends_on: list[str]

    async def run(self, targets: "PilotTargets", timeout: float) -> CheckOutcome: ...
