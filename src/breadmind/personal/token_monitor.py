"""Background token health monitor.

Periodically checks if OAuth tokens and API keys are still valid.
Sends notifications when tokens expire or become invalid.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from breadmind.utils.helpers import cancel_task_safely

logger = logging.getLogger(__name__)


@dataclass
class TokenStatus:
    service_id: str
    service_name: str
    healthy: bool
    message: str
    expires_in_hours: float | None = None
    last_checked: datetime | None = None


class TokenMonitor:
    """Monitors OAuth token and API key health."""

    def __init__(
        self,
        oauth_manager: Any = None,
        adapter_registry: Any = None,
        check_interval: int = 3600,  # 1 hour
        on_alert: Any = None,  # async callback(TokenStatus)
    ) -> None:
        self._oauth = oauth_manager
        self._registry = adapter_registry
        self._check_interval = check_interval
        self._on_alert = on_alert
        self._task: asyncio.Task | None = None
        self._statuses: dict[str, TokenStatus] = {}

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("TokenMonitor started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        await cancel_task_safely(self._task)

    async def check_all(self) -> list[TokenStatus]:
        """Check all token statuses. Returns list of all statuses."""
        statuses: list[TokenStatus] = []

        # Check OAuth tokens (Google, Microsoft)
        if self._oauth:
            for provider in ["google", "microsoft"]:
                status = await self._check_oauth(provider)
                statuses.append(status)
                self._statuses[status.service_id] = status

        return statuses

    async def get_statuses(self) -> dict[str, TokenStatus]:
        """Get last known statuses."""
        return dict(self._statuses)

    async def get_alerts(self) -> list[TokenStatus]:
        """Get only unhealthy or expiring-soon statuses."""
        return [
            s
            for s in self._statuses.values()
            if not s.healthy
            or (s.expires_in_hours is not None and s.expires_in_hours < 24)
        ]

    async def _loop(self) -> None:
        while True:
            try:
                statuses = await self.check_all()
                for status in statuses:
                    if not status.healthy or (
                        status.expires_in_hours is not None
                        and status.expires_in_hours < 1
                    ):
                        if self._on_alert:
                            await self._on_alert(status)
            except Exception:
                logger.exception("TokenMonitor check failed")
            await asyncio.sleep(self._check_interval)

    async def _check_oauth(self, provider: str) -> TokenStatus:
        """Check OAuth token health for a provider."""
        names = {"google": "Google", "microsoft": "Microsoft"}
        name = names.get(provider, provider)

        try:
            creds = await self._oauth.get_credentials(provider)
            if not creds:
                return TokenStatus(
                    service_id=f"oauth_{provider}",
                    service_name=name,
                    healthy=False,
                    message="인증되지 않음",
                    last_checked=datetime.now(timezone.utc),
                )

            expires_in = (creds.expires_at - time.time()) / 3600
            if creds.is_expired:
                return TokenStatus(
                    service_id=f"oauth_{provider}",
                    service_name=name,
                    healthy=False,
                    message="토큰 만료됨 — 재인증이 필요합니다",
                    expires_in_hours=expires_in,
                    last_checked=datetime.now(timezone.utc),
                )

            if expires_in < 1:
                return TokenStatus(
                    service_id=f"oauth_{provider}",
                    service_name=name,
                    healthy=True,
                    message=f"토큰이 {int(expires_in * 60)}분 후 만료 예정",
                    expires_in_hours=expires_in,
                    last_checked=datetime.now(timezone.utc),
                )

            return TokenStatus(
                service_id=f"oauth_{provider}",
                service_name=name,
                healthy=True,
                message="정상",
                expires_in_hours=expires_in,
                last_checked=datetime.now(timezone.utc),
            )

        except Exception as e:
            return TokenStatus(
                service_id=f"oauth_{provider}",
                service_name=name,
                healthy=False,
                message=f"상태 확인 실패: {e}",
                last_checked=datetime.now(timezone.utc),
            )
