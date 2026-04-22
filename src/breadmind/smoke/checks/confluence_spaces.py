"""GET /rest/api/space/{key} for each required space."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter

import httpx

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets


@dataclass
class ConfluenceSpacesCheck:
    email: str
    api_token: str
    name: str = "confluence_spaces"
    depends_on: list[str] = field(default_factory=lambda: ["confluence_auth"])

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        spaces = targets.confluence.required_spaces
        if not spaces:
            return CheckOutcome(
                name=self.name,
                status=CheckStatus.PASS,
                detail="no required spaces declared",
                duration_ms=int((perf_counter() - t0) * 1000),
            )

        async def _probe(c: httpx.AsyncClient, key: str) -> tuple[str, int, str]:
            try:
                r = await c.get(
                    f"{targets.confluence.base_url.rstrip('/')}/rest/api/space/{key}",
                    auth=(self.email, self.api_token),
                )
                return key, r.status_code, redact_secrets(r.text[:200])
            except Exception as exc:  # noqa: BLE001
                return key, 0, redact_secrets(str(exc))

        async with httpx.AsyncClient(timeout=timeout) as client:
            results = await asyncio.gather(*(_probe(client, k) for k in spaces))

        bad = [(k, code, body) for k, code, body in results if code != 200]
        if bad:
            parts = [f"{k}: HTTP {code or 'n/a'} {body}" for k, code, body in bad]
            return CheckOutcome(
                name=self.name,
                status=CheckStatus.FAIL,
                detail="; ".join(parts),
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name,
            status=CheckStatus.PASS,
            detail=f"{len(spaces)} spaces OK",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
