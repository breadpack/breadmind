"""GET /rest/api/user/current with basic auth (email:api_token)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter

import httpx

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets


@dataclass
class ConfluenceAuthCheck:
    email: str
    api_token: str
    name: str = "confluence_auth"
    depends_on: list[str] = field(
        default_factory=lambda: ["vault", "confluence_base_url"],
    )

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        url = f"{targets.confluence.base_url.rstrip('/')}/rest/api/user/current"
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, auth=(self.email, self.api_token))
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return CheckOutcome(name=self.name, status=CheckStatus.FAIL,
                                detail="timeout",
                                duration_ms=int((perf_counter() - t0) * 1000))
        except Exception as exc:  # noqa: BLE001
            return CheckOutcome(name=self.name, status=CheckStatus.FAIL,
                                detail=redact_secrets(str(exc)),
                                duration_ms=int((perf_counter() - t0) * 1000))

        if r.status_code != 200:
            body_preview = redact_secrets(r.text)
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"HTTP {r.status_code}: {body_preview}",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        try:
            payload = r.json()
        except ValueError as exc:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"HTTP 200 but body not JSON: {redact_secrets(str(exc))}",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        account_id = payload.get("accountId", "") if isinstance(payload, dict) else ""
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"account={account_id}",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
