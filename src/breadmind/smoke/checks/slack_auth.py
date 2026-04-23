"""Slack auth.test smoke check. Captures bot_user_id for downstream checks."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus


def _default_factory(token: str):
    from slack_sdk.web.async_client import AsyncWebClient
    return AsyncWebClient(token=token)


@dataclass
class SlackAuthCheck:
    token: str
    name: str = "slack_auth"
    depends_on: list[str] = field(default_factory=lambda: ["vault"])
    client_factory: Callable[[str], Any] = _default_factory
    bot_user_id: str = ""

    async def run(self, targets: Any, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        try:
            client = self.client_factory(self.token)
            resp = await asyncio.wait_for(client.auth_test(), timeout=timeout)
        except asyncio.TimeoutError:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail="timeout", duration_ms=int((perf_counter() - t0) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=redact_secrets(str(exc)),
                duration_ms=int((perf_counter() - t0) * 1000),
            )

        if not resp.get("ok"):
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail=redact_secrets(f"auth.test error={resp.get('error', 'unknown')}"),
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        self.bot_user_id = str(resp.get("user_id", ""))
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"user_id={self.bot_user_id} team={resp.get('team', '')}",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
