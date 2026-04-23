"""Declarative check: operator flipped no_training_confirmed after contract review."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets


@dataclass
class NoTrainingCheck:
    name: str = "llm_no_training"
    depends_on: list[str] = field(default_factory=lambda: ["config"])

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        if targets.llm.no_training_confirmed:
            return CheckOutcome(
                name=self.name, status=CheckStatus.PASS,
                detail="operator-confirmed",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.FAIL,
            detail=(
                "no_training_confirmed is false — review enterprise contract "
                "with Anthropic and Azure OpenAI, then set the flag in "
                "pilot-targets.yaml"
            ),
            duration_ms=int((perf_counter() - t0) * 1000),
        )
