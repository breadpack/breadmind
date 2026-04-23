"""The first check: load and validate ``pilot-targets.yaml``.

Unique in that it does not receive ``targets`` (it produces them). The
runner treats a FAIL here as exit code 2 and skips every other check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets, TargetsError, load_targets


@dataclass
class ConfigCheck:
    path: Path
    name: str = "config"
    depends_on: list[str] = field(default_factory=list)
    loaded: PilotTargets | None = None

    async def run(self, targets: Any, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        try:
            self.loaded = load_targets(self.path)
        except TargetsError as exc:
            return CheckOutcome(
                name=self.name,
                status=CheckStatus.FAIL,
                detail=redact_secrets(str(exc)),
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name,
            status=CheckStatus.PASS,
            detail=f"head={self.loaded.migration_head}",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
