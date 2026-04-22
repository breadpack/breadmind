"""Reject Confluence base URLs that are not https:// (P4 B6 rule)."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from urllib.parse import urlparse

from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets


@dataclass
class ConfluenceBaseUrlCheck:
    name: str = "confluence_base_url"
    depends_on: list[str] = field(default_factory=lambda: ["config"])

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        parsed = urlparse(targets.confluence.base_url)
        if parsed.scheme != "https":
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"scheme must be https, got '{parsed.scheme or 'none'}'",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        if not parsed.netloc:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail="base_url missing host",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=parsed.netloc,
            duration_ms=int((perf_counter() - t0) * 1000),
        )
