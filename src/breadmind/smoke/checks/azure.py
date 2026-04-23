"""GET {endpoint}/openai/deployments + required-deployment subset."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from time import perf_counter

import httpx

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.targets import PilotTargets

_API_VERSION = "2024-02-01"


@dataclass
class AzureOpenAICheck:
    name: str = "azure_openai"
    depends_on: list[str] = field(default_factory=lambda: ["config"])

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        env_name = targets.llm.azure.endpoint_env
        endpoint = os.environ.get(env_name, "")
        if not endpoint:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"{env_name} not set",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        key = os.environ.get("AZURE_OPENAI_KEY", "")
        if not key:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail="AZURE_OPENAI_KEY not set",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(
                    f"{endpoint.rstrip('/')}/openai/deployments",
                    params={"api-version": _API_VERSION},
                    headers={"api-key": key},
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
        ids = {d.get("id", "") for d in data if isinstance(d, dict)}
        missing = [d for d in targets.llm.azure.required_deployments if d not in ids]
        if missing:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=f"missing deployments: {', '.join(missing)}",
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"{len(targets.llm.azure.required_deployments)} deployments present",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
