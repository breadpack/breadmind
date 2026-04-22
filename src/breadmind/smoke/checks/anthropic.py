"""GET https://api.anthropic.com/v1/models + subset-of-required."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from time import perf_counter

import httpx

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets


@dataclass
class AnthropicCheck:
    name: str = "anthropic"
    depends_on: list[str] = field(default_factory=lambda: ["config"])
    base_url: str = "https://api.anthropic.com"

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail="ANTHROPIC_API_KEY not set",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(
                    f"{self.base_url}/v1/models",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                )
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return CheckOutcome(name=self.name, status=CheckStatus.FAIL,
                                detail="timeout",
                                duration_ms=int((perf_counter() - t0) * 1000))
        except Exception as exc:  # noqa: BLE001
            return CheckOutcome(name=self.name, status=CheckStatus.FAIL,
                                detail=redact_secrets(str(exc)),
                                duration_ms=int((perf_counter() - t0) * 1000))

        if r.status_code != 200:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"HTTP {r.status_code}: {redact_secrets(r.text)}",
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
        data = payload.get("data", []) if isinstance(payload, dict) else []
        ids = {m.get("id", "") for m in data if isinstance(m, dict)}
        missing = [m for m in targets.llm.anthropic.required_models if m not in ids]
        if missing:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"missing models: {', '.join(missing)}",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"{len(targets.llm.anthropic.required_models)} models present",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
