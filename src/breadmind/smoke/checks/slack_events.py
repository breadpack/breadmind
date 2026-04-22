"""Verify Socket Mode app token can open an apps.connections endpoint.

We only need a ``ws`` URL back; we do not actually connect. This proves
that the app-level token has the ``connections:write`` scope and Socket
Mode is enabled for the app — a common deploy-time gotcha.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.checks.slack_auth import _default_factory


@dataclass
class SlackEventsCheck:
    app_token: str
    name: str = "slack_events"
    depends_on: list[str] = field(default_factory=lambda: ["slack_auth"])
    client_factory: Callable[[str], Any] = _default_factory

    async def run(self, targets: Any, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        try:
            client = self.client_factory(self.app_token)
            resp = await asyncio.wait_for(
                client.apps_connections_open(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail="timeout",
                duration_ms=int((perf_counter() - t0) * 1000),
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
                detail=redact_secrets(
                    f"apps.connections.open error={resp.get('error', 'unknown')}",
                ),
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"ws={resp.get('url', '')[:40]}…",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
