"""For each required channel, assert the bot is a member."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from breadmind.smoke._redact import redact_secrets
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus
from breadmind.smoke.checks.slack_auth import _default_factory
from breadmind.smoke.targets import PilotTargets


@dataclass
class SlackChannelsCheck:
    token: str
    bot_user_id: str
    name: str = "slack_channels"
    depends_on: list[str] = field(default_factory=lambda: ["slack_auth"])
    client_factory: Callable[[str], Any] = _default_factory

    async def run(self, targets: PilotTargets, timeout: float) -> CheckOutcome:
        t0 = perf_counter()
        channels = targets.slack.required_channels
        if not channels:
            return CheckOutcome(
                name=self.name, status=CheckStatus.PASS,
                detail="no required channels declared",
                duration_ms=int((perf_counter() - t0) * 1000),
            )

        client = self.client_factory(self.token)

        async def _probe(ch: str) -> tuple[str, bool, str]:
            try:
                resp = await asyncio.wait_for(
                    client.conversations_members(channel=ch, cursor=""),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return ch, False, "timeout"
            except Exception as exc:  # noqa: BLE001
                return ch, False, redact_secrets(str(exc))
            if not resp.get("ok"):
                return ch, False, redact_secrets(f"error={resp.get('error', '')}")
            return ch, self.bot_user_id in resp.get("members", []), ""

        results = await asyncio.gather(*(_probe(c) for c in channels))
        missing = [(ch, reason) for ch, ok, reason in results if not ok]
        if missing:
            parts = [
                f"{ch}: {reason or 'bot not a member — /invite @BreadMind'}"
                for ch, reason in missing
            ]
            return CheckOutcome(
                name=self.name, status=CheckStatus.FAIL,
                detail="; ".join(parts),
                duration_ms=int((perf_counter() - t0) * 1000),
            )
        return CheckOutcome(
            name=self.name, status=CheckStatus.PASS,
            detail=f"{len(channels)} channels OK",
            duration_ms=int((perf_counter() - t0) * 1000),
        )
