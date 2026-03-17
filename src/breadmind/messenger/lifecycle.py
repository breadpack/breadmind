from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

from breadmind.messenger.auto_connect.base import GatewayState, HealthStatus
from breadmind.messenger.platforms import create_gateway, get_token_env_map

logger = logging.getLogger(__name__)


@dataclass
class GatewayStatus:
    platform: str
    state: GatewayState
    retry_count: int = 0
    last_error: str | None = None
    last_connected: float | None = None
    last_health_check: float | None = None


class GatewayLifecycleManager:
    """게이트웨이 자동 시작, 재시도, 상태 모니터링."""

    MAX_RETRIES = 10
    HEALTH_CHECK_INTERVAL = 30  # seconds
    BASE_BACKOFF = 1  # seconds
    MAX_BACKOFF = 300  # 5 minutes

    def __init__(self, message_router, db, event_callback=None):
        self._router = message_router
        self._db = db
        self._event_callback = event_callback
        self._statuses: dict[str, GatewayStatus] = {}
        self._health_task: asyncio.Task | None = None
        self._running = False

        for platform in get_token_env_map():
            self._statuses[platform] = GatewayStatus(
                platform=platform,
                state=GatewayState.UNCONFIGURED,
            )

    def _is_configured(self, platform: str) -> bool:
        """플랫폼에 필요한 토큰이 모두 설정되어 있는지 확인."""
        keys = get_token_env_map().get(platform, [])
        return all(os.environ.get(k) for k in keys)

    async def _load_tokens_from_db(self) -> None:
        """DB에서 토큰을 환경변수로 로드."""
        for platform, keys in get_token_env_map().items():
            for key in keys:
                if not os.environ.get(key):
                    result = await self._db.get_setting(f"messenger_token:{key}")
                    if result and isinstance(result, dict):
                        value = result.get("value")
                        if value:
                            os.environ[key] = value

    async def auto_start_all(self) -> dict[str, bool]:
        """설정된 모든 게이트웨이 자동 시작."""
        await self._load_tokens_from_db()
        results = {}

        for platform in get_token_env_map():
            auto_start = await self._db.get_setting(
                f"messenger_auto_start:{platform}"
            )
            if auto_start is not None and not auto_start:
                results[platform] = False
                continue

            if self._is_configured(platform):
                self._statuses[platform].state = GatewayState.CONFIGURED
                success = await self.start_gateway(platform)
                results[platform] = success
            else:
                results[platform] = False

        self._running = True
        self._health_task = asyncio.create_task(self._health_check_loop())
        logger.info("Gateway auto-start results: %s", results)
        return results

    async def start_gateway(self, platform: str) -> bool:
        """단일 게이트웨이 시작."""
        status = self._statuses[platform]
        status.state = GatewayState.CONNECTING
        status.retry_count = 0

        try:
            gateway = self._router._gateways.get(platform)
            if not gateway:
                gateway = await self._create_gateway(platform)
                if not gateway:
                    status.state = GatewayState.FAILED
                    status.last_error = "게이트웨이 생성 실패"
                    return False
                self._router.register_gateway(platform, gateway)

            await gateway.start()
            status.state = GatewayState.CONNECTED
            status.last_connected = time.time()
            status.last_error = None
            await self._emit_event("messenger_connected", platform)
            logger.info("Gateway started: %s", platform)
            return True

        except Exception as e:
            status.state = GatewayState.DISCONNECTED
            status.last_error = str(e)
            logger.warning("Gateway start failed for %s: %s", platform, e)
            asyncio.create_task(self._retry_connect(platform))
            return False

    async def stop_gateway(self, platform: str) -> bool:
        """단일 게이트웨이 중지."""
        try:
            gateway = self._router._gateways.get(platform)
            if gateway:
                await gateway.stop()
            self._statuses[platform].state = GatewayState.CONFIGURED
            await self._emit_event("messenger_disconnected", platform)
            return True
        except Exception as e:
            logger.warning("Gateway stop failed for %s: %s", platform, e)
            return False

    async def restart_gateway(self, platform: str) -> bool:
        """게이트웨이 재시작."""
        await self.stop_gateway(platform)
        return await self.start_gateway(platform)

    async def _retry_connect(self, platform: str) -> bool:
        """지수 백오프 재시도."""
        status = self._statuses[platform]
        while status.retry_count < self.MAX_RETRIES:
            status.retry_count += 1
            status.state = GatewayState.RECONNECTING
            backoff = min(
                self.BASE_BACKOFF * (2 ** (status.retry_count - 1)),
                self.MAX_BACKOFF,
            )
            logger.info(
                "Retrying %s in %ds (attempt %d/%d)",
                platform, backoff, status.retry_count, self.MAX_RETRIES,
            )
            await asyncio.sleep(backoff)

            try:
                gateway = self._router._gateways.get(platform)
                if gateway:
                    await gateway.start()
                    status.state = GatewayState.CONNECTED
                    status.last_connected = time.time()
                    status.last_error = None
                    await self._emit_event("messenger_reconnected", platform)
                    return True
            except Exception as e:
                status.last_error = str(e)

        status.state = GatewayState.FAILED
        await self._emit_event("messenger_failed", platform)
        logger.error("Gateway %s failed after %d retries", platform, self.MAX_RETRIES)
        return False

    async def _create_gateway(self, platform: str):
        """플랫폼에 맞는 게이트웨이 인스턴스 생성."""
        try:
            return await create_gateway(platform)
        except (ImportError, ValueError) as e:
            logger.warning("Cannot create gateway for %s: %s", platform, e)
        return None

    async def _health_check_loop(self) -> None:
        """주기적 health check 루프."""
        while self._running:
            try:
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                await self.health_check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Health check error: %s", e)

    async def health_check_all(self) -> dict[str, HealthStatus]:
        """모든 게이트웨이 상태 확인."""
        results = {}
        for platform, status in self._statuses.items():
            now = time.time()
            status.last_health_check = now

            if status.state == GatewayState.CONNECTED:
                gateway = self._router._gateways.get(platform)
                if not gateway:
                    status.state = GatewayState.DISCONNECTED
                    asyncio.create_task(self._retry_connect(platform))

            results[platform] = HealthStatus(
                platform=platform,
                state=status.state,
                last_check=str(now),
                error=status.last_error,
                retry_count=status.retry_count,
                uptime_seconds=(
                    now - status.last_connected
                    if status.last_connected and status.state == GatewayState.CONNECTED
                    else 0
                ),
            )
        return results

    def get_status(self, platform: str) -> GatewayStatus:
        """단일 플랫폼 상태 조회."""
        return self._statuses.get(
            platform,
            GatewayStatus(platform=platform, state=GatewayState.UNCONFIGURED),
        )

    def get_all_statuses(self) -> dict[str, GatewayStatus]:
        """모든 플랫폼 상태 조회."""
        return dict(self._statuses)

    async def shutdown(self) -> None:
        """매니저 종료."""
        self._running = False
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        await self._router.stop_all()

    async def _emit_event(self, event_type: str, platform: str) -> None:
        """이벤트 발행."""
        if self._event_callback:
            try:
                await self._event_callback(
                    {"type": event_type, "platform": platform}
                )
            except Exception as e:
                logger.warning("Event callback error: %s", e)
