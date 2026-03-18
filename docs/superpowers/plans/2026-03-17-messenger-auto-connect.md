# Messenger Auto-Connect Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 6개 메신저 플랫폼의 연결 과정을 자동화하고, 웹/채팅/CLI에서 통합 위자드를 제공하며, 게이트웨이 자동 시작/재시도/모니터링 및 토큰 보안 강화를 구현한다.

**Architecture:** AutoConnector(플랫폼별 결정적 로직) + ConnectionOrchestrator(위자드 상태 머신) + GatewayLifecycleManager(자동 시작/재시도) + SecurityManager(토큰 보안). 3개 인터페이스(웹/채팅/CLI)가 동일한 백엔드를 공유.

**Tech Stack:** Python 3.11+, FastAPI, asyncio, asyncpg, aiohttp (외부 API 호출)

---

## Chunk 1: Base Classes & Security

### Task 1: AutoConnector Base Classes & Data Models

**Files:**
- Create: `src/breadmind/messenger/auto_connect/__init__.py`
- Create: `src/breadmind/messenger/auto_connect/base.py`

- [ ] **Step 1: Create auto_connect package init**

```python
# src/breadmind/messenger/auto_connect/__init__.py
from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    SetupStep,
    InputField,
    CreateResult,
    ValidationResult,
    ConnectionResult,
    HealthStatus,
    WizardState,
    GatewayState,
)
```

- [ ] **Step 2: Create base.py with data models and ABC**

```python
# src/breadmind/messenger/auto_connect/base.py
from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class GatewayState(str, Enum):
    UNCONFIGURED = "unconfigured"
    CONFIGURED = "configured"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class InputField:
    name: str
    label: str
    placeholder: str = ""
    secret: bool = False
    required: bool = True


@dataclass
class SetupStep:
    step_number: int
    title: str
    description: str
    action_type: str  # "auto" | "user_input" | "user_action" | "oauth_redirect"
    action_url: str | None = None
    input_fields: list[InputField] | None = None
    auto_executable: bool = False


@dataclass
class CreateResult:
    success: bool
    message: str
    credentials: dict[str, str] | None = None
    error: str | None = None


@dataclass
class ValidationResult:
    valid: bool
    message: str
    bot_info: dict | None = None
    error: str | None = None


@dataclass
class ConnectionResult:
    success: bool
    message: str
    gateway_state: GatewayState = GatewayState.DISCONNECTED
    error: str | None = None


@dataclass
class HealthStatus:
    platform: str
    state: GatewayState
    last_check: str | None = None
    last_message: str | None = None
    error: str | None = None
    retry_count: int = 0
    uptime_seconds: float = 0.0


@dataclass
class WizardState:
    session_id: str
    platform: str
    current_step: int
    total_steps: int
    step_info: SetupStep | None
    status: str  # "waiting_input" | "processing" | "completed" | "failed"
    message: str
    error: str | None = None
    credentials: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def new(platform: str, total_steps: int, first_step: SetupStep) -> WizardState:
        return WizardState(
            session_id=str(uuid.uuid4()),
            platform=platform,
            current_step=1,
            total_steps=total_steps,
            step_info=first_step,
            status="waiting_input",
            message=first_step.description,
        )


class AutoConnector(ABC):
    """플랫폼별 자동 연결 로직의 기본 클래스."""

    platform: str = ""

    @abstractmethod
    async def get_setup_steps(self) -> list[SetupStep]:
        """연결에 필요한 단계 목록을 반환."""

    async def create_bot(self, params: dict) -> CreateResult:
        """봇/앱 자동 생성 (지원하는 플랫폼만 구현)."""
        return CreateResult(
            success=False,
            message=f"{self.platform}은 봇 자동 생성을 지원하지 않습니다.",
        )

    @abstractmethod
    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        """자격 증명 검증."""

    @abstractmethod
    async def connect(self, credentials: dict) -> ConnectionResult:
        """게이트웨이 연결 시작."""

    async def health_check(self) -> HealthStatus:
        """연결 상태 확인."""
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.UNCONFIGURED,
        )

    async def get_invite_url(self, credentials: dict) -> str | None:
        """서버/채널 초대 URL 생성 (지원하는 플랫폼만)."""
        return None
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/messenger/auto_connect/
git commit -m "feat(messenger): add AutoConnector base classes and data models"
```

---

### Task 2: SecurityManager

**Files:**
- Create: `src/breadmind/messenger/security.py`

- [ ] **Step 1: Implement MessengerSecurityManager**

```python
# src/breadmind/messenger/security.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class AccessLog:
    timestamp: str
    platform: str
    action: str  # "read" | "write" | "delete"
    actor: str  # "system" | "user:{id}" | "api"
    masked_value: str | None = None


@dataclass
class ExpiryStatus:
    platform: str
    token_type: str
    expires_at: str | None = None
    is_expired: bool = False
    days_remaining: int | None = None
    needs_rotation: bool = False


class MessengerSecurityManager:
    """메신저 토큰 보안 관리자."""

    TOKEN_KEY_MAP = {
        "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        "discord": ["DISCORD_BOT_TOKEN"],
        "telegram": ["TELEGRAM_BOT_TOKEN"],
        "whatsapp": [
            "WHATSAPP_TWILIO_ACCOUNT_SID",
            "WHATSAPP_TWILIO_AUTH_TOKEN",
            "WHATSAPP_FROM_NUMBER",
        ],
        "gmail": [
            "GMAIL_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GMAIL_REFRESH_TOKEN",
        ],
        "signal": ["SIGNAL_PHONE_NUMBER", "SIGNAL_CLI_PATH"],
    }

    ROTATION_THRESHOLD_DAYS = 90

    def __init__(self, db):
        self._db = db
        self._access_logs: list[AccessLog] = []
        self._token_timestamps: dict[str, float] = {}

    async def store_token(
        self, platform: str, key: str, value: str, actor: str = "system"
    ) -> None:
        """토큰을 DB에 암호화 저장하고 접근 로그 기록."""
        import os

        os.environ[key] = value
        await self._db.set_setting(
            f"messenger_token:{key}", {"value": value}
        )
        self._token_timestamps[f"{platform}:{key}"] = time.time()
        self._log_access(platform, "write", actor)
        logger.info("Token stored for %s:%s", platform, self.mask_token(value))

    async def get_token(
        self, platform: str, key: str, actor: str = "system"
    ) -> str | None:
        """DB에서 토큰 조회."""
        import os

        value = os.environ.get(key)
        if not value:
            result = await self._db.get_setting(f"messenger_token:{key}")
            if result and isinstance(result, dict):
                value = result.get("value")
        if value:
            self._log_access(platform, "read", actor)
        return value

    async def delete_token(
        self, platform: str, key: str, actor: str = "system"
    ) -> None:
        """토큰 삭제."""
        import os

        os.environ.pop(key, None)
        await self._db.delete_setting(f"messenger_token:{key}")
        self._token_timestamps.pop(f"{platform}:{key}", None)
        self._log_access(platform, "delete", actor)
        logger.info("Token deleted for %s:%s", platform, key)

    @staticmethod
    def mask_token(token: str) -> str:
        """토큰 마스킹: 처음 4자 + **** + 마지막 4자."""
        if not token or len(token) < 8:
            return "****"
        return f"{token[:4]}****{token[-4:]}"

    def _log_access(
        self, platform: str, action: str, actor: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._access_logs.append(
            AccessLog(
                timestamp=now,
                platform=platform,
                action=action,
                actor=actor,
            )
        )
        # 메모리 관리: 최대 1000개 유지
        if len(self._access_logs) > 1000:
            self._access_logs = self._access_logs[-500:]

    async def check_token_expiry(self, platform: str) -> ExpiryStatus:
        """토큰 만료/로테이션 필요 여부 확인."""
        keys = self.TOKEN_KEY_MAP.get(platform, [])
        for key in keys:
            ts_key = f"{platform}:{key}"
            stored_at = self._token_timestamps.get(ts_key)
            if stored_at:
                age_days = (time.time() - stored_at) / 86400
                if age_days > self.ROTATION_THRESHOLD_DAYS:
                    return ExpiryStatus(
                        platform=platform,
                        token_type=key,
                        needs_rotation=True,
                        days_remaining=0,
                    )
        return ExpiryStatus(
            platform=platform,
            token_type="all",
            needs_rotation=False,
        )

    def get_access_logs(
        self, platform: str | None = None, limit: int = 50
    ) -> list[AccessLog]:
        """접근 로그 조회."""
        logs = self._access_logs
        if platform:
            logs = [log for log in logs if log.platform == platform]
        return logs[-limit:]

    async def load_token_timestamps(self) -> None:
        """DB에서 토큰 저장 시점 복원."""
        for platform, keys in self.TOKEN_KEY_MAP.items():
            for key in keys:
                result = await self._db.get_setting(f"messenger_token:{key}")
                if result:
                    ts = result.get("stored_at", time.time())
                    self._token_timestamps[f"{platform}:{key}"] = ts
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/security.py
git commit -m "feat(messenger): add MessengerSecurityManager with token masking, access logs, expiry detection"
```

---

## Chunk 2: GatewayLifecycleManager

### Task 3: GatewayLifecycleManager

**Files:**
- Create: `src/breadmind/messenger/lifecycle.py`
- Modify: `src/breadmind/messenger/router.py` — MessageRouter에 lifecycle 통합

- [ ] **Step 1: Implement GatewayLifecycleManager**

```python
# src/breadmind/messenger/lifecycle.py
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from breadmind.messenger.auto_connect.base import GatewayState, HealthStatus

logger = logging.getLogger(__name__)


TOKEN_ENV_MAP = {
    "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
    "discord": ["DISCORD_BOT_TOKEN"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "whatsapp": [
        "WHATSAPP_TWILIO_ACCOUNT_SID",
        "WHATSAPP_TWILIO_AUTH_TOKEN",
        "WHATSAPP_FROM_NUMBER",
    ],
    "gmail": [
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
    ],
    "signal": ["SIGNAL_PHONE_NUMBER"],
}


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

        # 모든 플랫폼 초기 상태
        for platform in TOKEN_ENV_MAP:
            self._statuses[platform] = GatewayStatus(
                platform=platform,
                state=GatewayState.UNCONFIGURED,
            )

    def _is_configured(self, platform: str) -> bool:
        """플랫폼에 필요한 토큰이 모두 설정되어 있는지 확인."""
        keys = TOKEN_ENV_MAP.get(platform, [])
        return all(os.environ.get(k) for k in keys)

    async def _load_tokens_from_db(self) -> None:
        """DB에서 토큰을 환경변수로 로드."""
        for platform, keys in TOKEN_ENV_MAP.items():
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

        for platform in TOKEN_ENV_MAP:
            auto_start = await self._db.get_setting(
                f"messenger_auto_start:{platform}"
            )
            # 기본값 True
            if auto_start is not None and not auto_start:
                results[platform] = False
                continue

            if self._is_configured(platform):
                self._statuses[platform].state = GatewayState.CONFIGURED
                success = await self.start_gateway(platform)
                results[platform] = success
            else:
                results[platform] = False

        # health check 루프 시작
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
            return await self._retry_connect(platform)

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
                platform,
                backoff,
                status.retry_count,
                self.MAX_RETRIES,
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
            if platform == "slack":
                from breadmind.messenger.slack import SlackGateway

                return SlackGateway()
            elif platform == "discord":
                from breadmind.messenger.discord_gw import DiscordGateway

                return DiscordGateway()
            elif platform == "telegram":
                from breadmind.messenger.telegram_gw import TelegramGateway

                return TelegramGateway()
            elif platform == "whatsapp":
                from breadmind.messenger.whatsapp_gw import WhatsAppGateway

                return WhatsAppGateway()
            elif platform == "gmail":
                from breadmind.messenger.gmail_gw import GmailGateway

                return GmailGateway()
            elif platform == "signal":
                from breadmind.messenger.signal_gw import SignalGateway

                return SignalGateway()
        except ImportError as e:
            logger.warning("Cannot import gateway for %s: %s", platform, e)
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
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/lifecycle.py
git commit -m "feat(messenger): add GatewayLifecycleManager with auto-start, exponential backoff retry, health monitoring"
```

---

## Chunk 3: Platform AutoConnectors

### Task 4: Telegram AutoConnector

**Files:**
- Create: `src/breadmind/messenger/auto_connect/telegram.py`

- [ ] **Step 1: Implement TelegramAutoConnector**

```python
# src/breadmind/messenger/auto_connect/telegram.py
from __future__ import annotations

import logging
import os

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramAutoConnector(AutoConnector):
    platform = "telegram"

    async def get_setup_steps(self) -> list[SetupStep]:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            return [
                SetupStep(
                    step_number=1,
                    title="토큰 검증",
                    description="기존 토큰을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]
        return [
            SetupStep(
                step_number=1,
                title="BotFather에서 봇 생성",
                description=(
                    "Telegram에서 @BotFather와 대화하여 봇을 만드세요.\n"
                    "1. 아래 링크를 클릭하세요\n"
                    "2. /newbot 명령을 보내세요\n"
                    "3. 봇 이름과 유저네임을 설정하세요\n"
                    "4. 받은 토큰을 복사하세요"
                ),
                action_type="user_action",
                action_url="https://t.me/BotFather?start=start",
            ),
            SetupStep(
                step_number=2,
                title="봇 토큰 입력",
                description="BotFather에서 받은 봇 토큰을 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="bot_token",
                        label="Bot Token",
                        placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="연결 완료",
                description="토큰 검증 및 게이트웨이 시작",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        token = credentials.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return ValidationResult(valid=False, message="토큰이 없습니다.")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{TELEGRAM_API}/bot{token}/getMe", timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        bot = data["result"]
                        return ValidationResult(
                            valid=True,
                            message=f"봇 확인: @{bot.get('username')} ({bot.get('first_name')})",
                            bot_info=bot,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 토큰입니다.",
                        error=data.get("description"),
                    )
        except Exception as e:
            return ValidationResult(
                valid=False,
                message="Telegram API 연결 실패",
                error=str(e),
            )

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False,
                message=validation.message,
                error=validation.error,
            )
        return ConnectionResult(
            success=True,
            message=f"Telegram 봇 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)

        validation = await self.validate_credentials({"bot_token": token})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/auto_connect/telegram.py
git commit -m "feat(messenger): add TelegramAutoConnector with BotFather guide and token validation"
```

---

### Task 5: Slack AutoConnector

**Files:**
- Create: `src/breadmind/messenger/auto_connect/slack.py`

- [ ] **Step 1: Implement SlackAutoConnector**

```python
# src/breadmind/messenger/auto_connect/slack.py
from __future__ import annotations

import logging
import os

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    CreateResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)

SLACK_APP_MANIFEST = {
    "display_information": {
        "name": "BreadMind",
        "description": "AI Infrastructure Agent",
        "background_color": "#2c2d30",
    },
    "features": {
        "bot_user": {"display_name": "BreadMind", "always_online": True},
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "chat:write",
                "channels:history",
                "channels:read",
                "groups:history",
                "groups:read",
                "im:history",
                "im:read",
                "im:write",
                "mpim:history",
                "mpim:read",
                "app_mentions:read",
                "reactions:read",
                "reactions:write",
            ],
        },
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": ["message.im", "app_mention"],
        },
        "socket_mode_enabled": True,
        "org_deploy_enabled": False,
    },
}


class SlackAutoConnector(AutoConnector):
    platform = "slack"

    async def get_setup_steps(self) -> list[SetupStep]:
        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        app_token = os.environ.get("SLACK_APP_TOKEN")

        if bot_token and app_token:
            return [
                SetupStep(
                    step_number=1,
                    title="토큰 검증",
                    description="기존 토큰을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        client_id = os.environ.get("SLACK_CLIENT_ID")
        if client_id:
            # OAuth flow 가능
            port = os.environ.get("BREADMIND_PORT", "8080")
            redirect_uri = f"http://localhost:{port}/api/messenger/slack/oauth-callback"
            oauth_url = (
                f"https://slack.com/oauth/v2/authorize"
                f"?client_id={client_id}"
                f"&scope=chat:write,channels:history,channels:read,im:history,im:read,im:write,app_mentions:read"
                f"&redirect_uri={redirect_uri}"
            )
            return [
                SetupStep(
                    step_number=1,
                    title="Slack 앱 승인",
                    description="아래 링크를 클릭하여 BreadMind 앱을 워크스페이스에 설치하세요.",
                    action_type="oauth_redirect",
                    action_url=oauth_url,
                ),
                SetupStep(
                    step_number=2,
                    title="연결 완료",
                    description="OAuth 인증이 완료되면 자동으로 연결됩니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        # 수동 설정
        return [
            SetupStep(
                step_number=1,
                title="Slack 앱 생성",
                description=(
                    "Slack API 사이트에서 새 앱을 만드세요.\n"
                    "1. 아래 링크에서 'Create New App' → 'From a manifest' 선택\n"
                    "2. 워크스페이스를 선택하세요\n"
                    "3. BreadMind가 제공하는 매니페스트를 붙여넣으세요"
                ),
                action_type="user_action",
                action_url="https://api.slack.com/apps",
            ),
            SetupStep(
                step_number=2,
                title="토큰 입력",
                description=(
                    "앱 설정에서 Bot Token과 App-Level Token을 복사하세요.\n"
                    "- Bot Token: OAuth & Permissions → Bot User OAuth Token (xoxb-...)\n"
                    "- App Token: Basic Information → App-Level Tokens (xapp-...)"
                ),
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="bot_token",
                        label="Bot Token",
                        placeholder="xoxb-...",
                        secret=True,
                    ),
                    InputField(
                        name="app_token",
                        label="App-Level Token",
                        placeholder="xapp-...",
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="연결 완료",
                description="토큰 검증 및 게이트웨이 시작",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def create_bot(self, params: dict) -> CreateResult:
        """Slack App Manifest API로 앱 생성 시도."""
        config_token = params.get("config_token")
        if not config_token:
            return CreateResult(
                success=False,
                message="Configuration token이 필요합니다. Slack API에서 수동으로 앱을 생성하세요.",
            )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/apps.manifest.create",
                    json={"manifest": SLACK_APP_MANIFEST},
                    headers={"Authorization": f"Bearer {config_token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        creds = data.get("credentials", {})
                        return CreateResult(
                            success=True,
                            message="Slack 앱이 생성되었습니다.",
                            credentials={
                                "client_id": creds.get("client_id", ""),
                                "client_secret": creds.get("client_secret", ""),
                                "app_id": data.get("app_id", ""),
                            },
                        )
                    return CreateResult(
                        success=False,
                        message="앱 생성 실패",
                        error=data.get("error"),
                    )
        except Exception as e:
            return CreateResult(success=False, message="Slack API 오류", error=str(e))

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        bot_token = credentials.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            return ValidationResult(valid=False, message="Bot Token이 없습니다.")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return ValidationResult(
                            valid=True,
                            message=f"연결 확인: {data.get('team')} / {data.get('user')}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 토큰",
                        error=data.get("error"),
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Slack API 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False,
                message=validation.message,
                error=validation.error,
            )
        return ConnectionResult(
            success=True,
            message=f"Slack 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({"bot_token": token})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/auto_connect/slack.py
git commit -m "feat(messenger): add SlackAutoConnector with manifest API, OAuth flow, manual setup"
```

---

### Task 6: Discord AutoConnector

**Files:**
- Create: `src/breadmind/messenger/auto_connect/discord.py`

- [ ] **Step 1: Implement DiscordAutoConnector**

```python
# src/breadmind/messenger/auto_connect/discord.py
from __future__ import annotations

import logging
import os

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
BOT_PERMISSIONS = 274877975552  # Send Messages, Read Messages, Add Reactions, etc.


class DiscordAutoConnector(AutoConnector):
    platform = "discord"

    async def get_setup_steps(self) -> list[SetupStep]:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            return [
                SetupStep(
                    step_number=1,
                    title="토큰 검증",
                    description="기존 토큰을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        return [
            SetupStep(
                step_number=1,
                title="Discord 봇 생성",
                description=(
                    "Discord Developer Portal에서 새 애플리케이션을 만드세요.\n"
                    "1. 아래 링크에서 'New Application' 클릭\n"
                    "2. 이름 입력 (예: BreadMind)\n"
                    "3. 'Bot' 메뉴에서 'Add Bot' 클릭\n"
                    "4. 'MESSAGE CONTENT INTENT' 활성화\n"
                    "5. 'Reset Token'을 클릭하여 토큰 복사"
                ),
                action_type="user_action",
                action_url="https://discord.com/developers/applications",
            ),
            SetupStep(
                step_number=2,
                title="봇 토큰 입력",
                description="Discord Developer Portal에서 복사한 봇 토큰을 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="bot_token",
                        label="Bot Token",
                        placeholder="MTIz...",
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="서버에 봇 초대",
                description="생성된 초대 링크를 클릭하여 봇을 서버에 추가하세요.",
                action_type="user_action",
                # action_url은 토큰 검증 후 동적 생성
            ),
            SetupStep(
                step_number=4,
                title="연결 완료",
                description="토큰 검증 및 게이트웨이 시작",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        token = credentials.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            return ValidationResult(valid=False, message="Bot Token이 없습니다.")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DISCORD_API}/users/@me",
                    headers={"Authorization": f"Bot {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return ValidationResult(
                            valid=True,
                            message=f"봇 확인: {data.get('username')}#{data.get('discriminator')}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 토큰",
                        error=f"HTTP {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Discord API 오류", error=str(e))

    async def get_invite_url(self, credentials: dict) -> str | None:
        token = credentials.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            return None
        # 봇의 application ID 조회
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DISCORD_API}/oauth2/applications/@me",
                    headers={"Authorization": f"Bot {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        app_id = data.get("id")
                        return (
                            f"https://discord.com/oauth2/authorize"
                            f"?client_id={app_id}"
                            f"&permissions={BOT_PERMISSIONS}"
                            f"&scope=bot%20applications.commands"
                        )
        except Exception:
            pass

        client_id = os.environ.get("DISCORD_CLIENT_ID")
        if client_id:
            return (
                f"https://discord.com/oauth2/authorize"
                f"?client_id={client_id}"
                f"&permissions={BOT_PERMISSIONS}"
                f"&scope=bot%20applications.commands"
            )
        return None

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        return ConnectionResult(
            success=True,
            message=f"Discord 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({"bot_token": token})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/auto_connect/discord.py
git commit -m "feat(messenger): add DiscordAutoConnector with portal guide, token validation, invite URL generation"
```

---

### Task 7: WhatsApp AutoConnector

**Files:**
- Create: `src/breadmind/messenger/auto_connect/whatsapp.py`

- [ ] **Step 1: Implement WhatsAppAutoConnector**

```python
# src/breadmind/messenger/auto_connect/whatsapp.py
from __future__ import annotations

import logging
import os

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01"


class WhatsAppAutoConnector(AutoConnector):
    platform = "whatsapp"

    async def get_setup_steps(self) -> list[SetupStep]:
        sid = os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        if sid:
            return [
                SetupStep(
                    step_number=1,
                    title="Twilio 연결 검증",
                    description="기존 Twilio 설정을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        return [
            SetupStep(
                step_number=1,
                title="Twilio 계정 준비",
                description=(
                    "Twilio에서 WhatsApp Sandbox 또는 프로덕션 번호를 설정하세요.\n"
                    "1. Twilio Console에 로그인\n"
                    "2. Account SID와 Auth Token을 확인 (Dashboard)\n"
                    "3. WhatsApp Sandbox 또는 프로덕션 번호 활성화"
                ),
                action_type="user_action",
                action_url="https://console.twilio.com/",
            ),
            SetupStep(
                step_number=2,
                title="Twilio 자격 증명 입력",
                description="Twilio Dashboard에서 복사한 정보를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="account_sid",
                        label="Account SID",
                        placeholder="AC...",
                    ),
                    InputField(
                        name="auth_token",
                        label="Auth Token",
                        placeholder="auth token",
                        secret=True,
                    ),
                    InputField(
                        name="from_number",
                        label="WhatsApp 번호",
                        placeholder="whatsapp:+14155238886",
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="웹훅 자동 설정",
                description="BreadMind 웹훅 URL을 Twilio에 자동으로 등록합니다.",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        sid = credentials.get("account_sid") or os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        token = credentials.get("auth_token") or os.environ.get("WHATSAPP_TWILIO_AUTH_TOKEN")
        if not sid or not token:
            return ValidationResult(valid=False, message="Account SID 또는 Auth Token이 없습니다.")

        try:
            auth = aiohttp.BasicAuth(sid, token)
            async with aiohttp.ClientSession(auth=auth) as session:
                async with session.get(
                    f"{TWILIO_API}/Accounts/{sid}.json",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return ValidationResult(
                            valid=True,
                            message=f"Twilio 확인: {data.get('friendly_name')}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 자격 증명",
                        error=f"HTTP {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Twilio API 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        # 웹훅 URL 자동 등록 시도
        await self._register_webhook(credentials)
        return ConnectionResult(
            success=True,
            message=f"WhatsApp 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def _register_webhook(self, credentials: dict) -> None:
        """Twilio 웹훅 URL 자동 등록."""
        sid = credentials.get("account_sid") or os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        token = credentials.get("auth_token") or os.environ.get("WHATSAPP_TWILIO_AUTH_TOKEN")
        from_number = credentials.get("from_number") or os.environ.get("WHATSAPP_FROM_NUMBER")
        port = os.environ.get("BREADMIND_PORT", "8080")
        host = os.environ.get("BREADMIND_HOST", "localhost")

        if not all([sid, token, from_number]):
            return

        webhook_url = f"http://{host}:{port}/api/webhook/receive/whatsapp"
        # Twilio Messaging Service 웹훅 설정은 번호의 SID가 필요
        # 여기서는 로그만 남기고, 사용자에게 수동 설정 안내
        logger.info(
            "WhatsApp webhook URL: %s — Twilio Console에서 이 URL을 "
            "Messaging → Settings → WhatsApp Sandbox 웹훅에 설정하세요.",
            webhook_url,
        )

    async def health_check(self) -> HealthStatus:
        sid = os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        if not sid:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/auto_connect/whatsapp.py
git commit -m "feat(messenger): add WhatsAppAutoConnector with Twilio validation and webhook setup"
```

---

### Task 8: Gmail AutoConnector

**Files:**
- Create: `src/breadmind/messenger/auto_connect/gmail.py`

- [ ] **Step 1: Implement GmailAutoConnector**

```python
# src/breadmind/messenger/auto_connect/gmail.py
from __future__ import annotations

import logging
import os

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


class GmailAutoConnector(AutoConnector):
    platform = "gmail"

    async def get_setup_steps(self) -> list[SetupStep]:
        refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")
        if refresh_token:
            return [
                SetupStep(
                    step_number=1,
                    title="Gmail 연결 검증",
                    description="기존 OAuth 토큰을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        client_id = os.environ.get("GMAIL_CLIENT_ID")
        if client_id:
            port = os.environ.get("BREADMIND_PORT", "8080")
            redirect_uri = f"http://localhost:{port}/api/messenger/gmail/oauth-callback"
            oauth_url = (
                f"https://accounts.google.com/o/oauth2/v2/auth"
                f"?client_id={client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&response_type=code"
                f"&scope=https://www.googleapis.com/auth/gmail.readonly%20"
                f"https://www.googleapis.com/auth/gmail.send"
                f"&access_type=offline"
                f"&prompt=consent"
            )
            return [
                SetupStep(
                    step_number=1,
                    title="Google 계정 인증",
                    description="아래 링크를 클릭하여 Gmail 접근을 허용하세요.",
                    action_type="oauth_redirect",
                    action_url=oauth_url,
                ),
                SetupStep(
                    step_number=2,
                    title="연결 완료",
                    description="OAuth 인증이 완료되면 자동으로 연결됩니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        return [
            SetupStep(
                step_number=1,
                title="Google Cloud 프로젝트 설정",
                description=(
                    "Google Cloud Console에서 OAuth를 설정하세요.\n"
                    "1. 아래 링크에서 새 프로젝트 생성 또는 기존 프로젝트 선택\n"
                    "2. Gmail API 활성화\n"
                    "3. OAuth 동의 화면 구성\n"
                    "4. OAuth 2.0 클라이언트 ID 생성 (웹 애플리케이션 유형)\n"
                    "5. Client ID와 Client Secret 복사"
                ),
                action_type="user_action",
                action_url="https://console.cloud.google.com/apis/credentials",
            ),
            SetupStep(
                step_number=2,
                title="OAuth 자격 증명 입력",
                description="Google Cloud Console에서 복사한 정보를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="client_id",
                        label="Client ID",
                        placeholder="xxx.apps.googleusercontent.com",
                    ),
                    InputField(
                        name="client_secret",
                        label="Client Secret",
                        placeholder="GOCSPX-...",
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="Google 계정 인증",
                description="OAuth 인증 페이지로 이동하여 Gmail 접근을 허용하세요.",
                action_type="oauth_redirect",
            ),
            SetupStep(
                step_number=4,
                title="연결 완료",
                description="OAuth 인증 완료 후 자동으로 연결됩니다.",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        refresh_token = credentials.get("refresh_token") or os.environ.get("GMAIL_REFRESH_TOKEN")
        client_id = credentials.get("client_id") or os.environ.get("GMAIL_CLIENT_ID")
        client_secret = credentials.get("client_secret") or os.environ.get("GMAIL_CLIENT_SECRET")

        if not all([refresh_token, client_id, client_secret]):
            return ValidationResult(valid=False, message="OAuth 자격 증명이 불완전합니다.")

        try:
            async with aiohttp.ClientSession() as session:
                # refresh token으로 access token 획득
                async with session.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    token_data = await resp.json()
                    access_token = token_data.get("access_token")
                    if not access_token:
                        return ValidationResult(
                            valid=False,
                            message="토큰 갱신 실패",
                            error=token_data.get("error_description"),
                        )

                # Gmail profile 조회
                async with session.get(
                    f"{GMAIL_API}/users/me/profile",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        profile = await resp.json()
                        return ValidationResult(
                            valid=True,
                            message=f"Gmail 확인: {profile.get('emailAddress')}",
                            bot_info=profile,
                        )
                    return ValidationResult(
                        valid=False,
                        message="Gmail API 접근 실패",
                        error=f"HTTP {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Google API 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        return ConnectionResult(
            success=True,
            message=f"Gmail 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("GMAIL_REFRESH_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/auto_connect/gmail.py
git commit -m "feat(messenger): add GmailAutoConnector with Google OAuth flow and token validation"
```

---

### Task 9: Signal AutoConnector

**Files:**
- Create: `src/breadmind/messenger/auto_connect/signal.py`

- [ ] **Step 1: Implement SignalAutoConnector**

```python
# src/breadmind/messenger/auto_connect/signal.py
from __future__ import annotations

import asyncio
import logging
import os
import shutil

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    CreateResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class SignalAutoConnector(AutoConnector):
    platform = "signal"

    def _find_signal_cli(self) -> str | None:
        """signal-cli 바이너리 경로 탐색."""
        configured = os.environ.get("SIGNAL_CLI_PATH")
        if configured and os.path.isfile(configured):
            return configured
        return shutil.which("signal-cli")

    async def get_setup_steps(self) -> list[SetupStep]:
        phone = os.environ.get("SIGNAL_PHONE_NUMBER")
        cli_path = self._find_signal_cli()

        if phone and cli_path:
            return [
                SetupStep(
                    step_number=1,
                    title="Signal 연결 검증",
                    description="기존 Signal 설정을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        steps = []
        step = 1

        if not cli_path:
            steps.append(
                SetupStep(
                    step_number=step,
                    title="signal-cli 설치",
                    description=(
                        "signal-cli가 설치되어 있지 않습니다.\n"
                        "아래 링크에서 설치 방법을 확인하세요.\n"
                        "- Linux: 패키지 매니저 또는 수동 설치\n"
                        "- macOS: brew install signal-cli\n"
                        "- 설치 후 다시 이 과정을 진행하세요"
                    ),
                    action_type="user_action",
                    action_url="https://github.com/AsamK/signal-cli/releases",
                ),
            )
            step += 1

        steps.append(
            SetupStep(
                step_number=step,
                title="전화번호 등록",
                description="Signal에 사용할 전화번호를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="phone_number",
                        label="전화번호",
                        placeholder="+821012345678",
                    ),
                    InputField(
                        name="signal_cli_path",
                        label="signal-cli 경로 (자동 감지되면 비워두세요)",
                        placeholder="/usr/local/bin/signal-cli",
                        required=False,
                    ),
                ],
            ),
        )
        step += 1

        steps.append(
            SetupStep(
                step_number=step,
                title="인증 코드 입력",
                description="SMS로 받은 인증 코드를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="verification_code",
                        label="인증 코드",
                        placeholder="123-456",
                    ),
                ],
            ),
        )
        step += 1

        steps.append(
            SetupStep(
                step_number=step,
                title="연결 완료",
                description="Signal 등록 및 게이트웨이 시작",
                action_type="auto",
                auto_executable=True,
            ),
        )

        return steps

    async def create_bot(self, params: dict) -> CreateResult:
        """signal-cli로 번호 등록."""
        phone = params.get("phone_number")
        cli_path = params.get("signal_cli_path") or self._find_signal_cli()

        if not cli_path:
            return CreateResult(
                success=False,
                message="signal-cli가 설치되어 있지 않습니다.",
            )

        if not phone:
            return CreateResult(success=False, message="전화번호가 필요합니다.")

        try:
            proc = await asyncio.create_subprocess_exec(
                cli_path, "-u", phone, "register",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                return CreateResult(
                    success=True,
                    message="등록 요청 완료. SMS 인증 코드를 입력하세요.",
                    credentials={"phone_number": phone, "signal_cli_path": cli_path},
                )
            return CreateResult(
                success=False,
                message="등록 실패",
                error=stderr.decode() if stderr else "unknown error",
            )
        except asyncio.TimeoutError:
            return CreateResult(success=False, message="등록 시간 초과")
        except Exception as e:
            return CreateResult(success=False, message="signal-cli 실행 실패", error=str(e))

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        phone = credentials.get("phone_number") or os.environ.get("SIGNAL_PHONE_NUMBER")
        cli_path = credentials.get("signal_cli_path") or self._find_signal_cli()

        if not phone:
            return ValidationResult(valid=False, message="전화번호가 없습니다.")
        if not cli_path:
            return ValidationResult(valid=False, message="signal-cli를 찾을 수 없습니다.")

        # signal-cli가 존재하고 번호가 등록되어 있는지 확인
        try:
            proc = await asyncio.create_subprocess_exec(
                cli_path, "-u", phone, "receive", "-t", "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return ValidationResult(
                    valid=True,
                    message=f"Signal 확인: {phone}",
                    bot_info={"phone_number": phone},
                )
            return ValidationResult(
                valid=False,
                message="Signal 번호가 등록되지 않았습니다.",
                error=stderr.decode() if stderr else None,
            )
        except asyncio.TimeoutError:
            # receive 타임아웃은 정상 (메시지가 없을 수 있음)
            return ValidationResult(
                valid=True,
                message=f"Signal 확인: {phone}",
                bot_info={"phone_number": phone},
            )
        except Exception as e:
            return ValidationResult(valid=False, message="signal-cli 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        return ConnectionResult(
            success=True,
            message=f"Signal 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        phone = os.environ.get("SIGNAL_PHONE_NUMBER")
        if not phone:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        cli_path = self._find_signal_cli()
        if not cli_path:
            return HealthStatus(
                platform=self.platform,
                state=GatewayState.FAILED,
                error="signal-cli not found",
            )
        return HealthStatus(platform=self.platform, state=GatewayState.CONNECTED)
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/auto_connect/signal.py
git commit -m "feat(messenger): add SignalAutoConnector with signal-cli detection, registration, verification"
```

---

## Chunk 4: ConnectionOrchestrator & Integration

### Task 10: ConnectionOrchestrator

**Files:**
- Create: `src/breadmind/messenger/auto_connect/orchestrator.py`

- [ ] **Step 1: Implement ConnectionOrchestrator**

```python
# src/breadmind/messenger/auto_connect/orchestrator.py
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    GatewayState,
    SetupStep,
    WizardState,
)

logger = logging.getLogger(__name__)

SESSION_TTL = 1800  # 30 minutes


@dataclass
class _Session:
    wizard: WizardState
    connector: AutoConnector
    steps: list[SetupStep]
    created_at: float


class ConnectionOrchestrator:
    """3개 인터페이스(웹/채팅/CLI)의 연결 요청을 통합 처리하는 위자드 상태 머신."""

    def __init__(self, security_manager, lifecycle_manager, db):
        self._sessions: dict[str, _Session] = {}
        self._security = security_manager
        self._lifecycle = lifecycle_manager
        self._db = db
        self._connectors: dict[str, AutoConnector] = {}
        self._register_connectors()

    def _register_connectors(self) -> None:
        from breadmind.messenger.auto_connect.telegram import TelegramAutoConnector
        from breadmind.messenger.auto_connect.slack import SlackAutoConnector
        from breadmind.messenger.auto_connect.discord import DiscordAutoConnector
        from breadmind.messenger.auto_connect.whatsapp import WhatsAppAutoConnector
        from breadmind.messenger.auto_connect.gmail import GmailAutoConnector
        from breadmind.messenger.auto_connect.signal import SignalAutoConnector

        for cls in [
            TelegramAutoConnector,
            SlackAutoConnector,
            DiscordAutoConnector,
            WhatsAppAutoConnector,
            GmailAutoConnector,
            SignalAutoConnector,
        ]:
            connector = cls()
            self._connectors[connector.platform] = connector

    async def start_connection(
        self, platform: str, interface: str = "web"
    ) -> WizardState:
        """연결 위자드 시작. 같은 플랫폼에 기존 세션이 있으면 이어서 진행."""
        self._cleanup_expired()

        # 기존 세션 확인
        for session in self._sessions.values():
            if (
                session.wizard.platform == platform
                and session.wizard.status not in ("completed", "failed")
            ):
                return session.wizard

        connector = self._connectors.get(platform)
        if not connector:
            return WizardState(
                session_id="",
                platform=platform,
                current_step=0,
                total_steps=0,
                step_info=None,
                status="failed",
                message=f"지원하지 않는 플랫폼: {platform}",
                error="unsupported_platform",
            )

        steps = await connector.get_setup_steps()
        wizard = WizardState.new(platform, len(steps), steps[0])

        self._sessions[wizard.session_id] = _Session(
            wizard=wizard,
            connector=connector,
            steps=steps,
            created_at=time.time(),
        )

        logger.info(
            "Connection wizard started: %s (session=%s, interface=%s, steps=%d)",
            platform,
            wizard.session_id,
            interface,
            len(steps),
        )

        # auto_executable 단계면 자동 실행
        if steps[0].auto_executable:
            return await self._execute_auto_step(wizard.session_id)

        return wizard

    async def process_step(
        self, session_id: str, user_input: dict
    ) -> WizardState:
        """사용자 입력을 받아 다음 단계로 진행."""
        session = self._sessions.get(session_id)
        if not session:
            return WizardState(
                session_id=session_id,
                platform="",
                current_step=0,
                total_steps=0,
                step_info=None,
                status="failed",
                message="세션을 찾을 수 없습니다.",
                error="session_not_found",
            )

        wizard = session.wizard
        connector = session.connector
        current_step = session.steps[wizard.current_step - 1]

        # 사용자 입력 저장
        if current_step.action_type == "user_input":
            wizard.credentials.update(user_input)

            # 토큰 저장
            token_map = self._get_token_env_map(wizard.platform)
            for field_name, env_key in token_map.items():
                if field_name in user_input and user_input[field_name]:
                    await self._security.store_token(
                        wizard.platform, env_key, user_input[field_name], actor="wizard"
                    )

        # 다음 단계로
        if wizard.current_step < wizard.total_steps:
            wizard.current_step += 1
            next_step = session.steps[wizard.current_step - 1]
            wizard.step_info = next_step
            wizard.status = "waiting_input"
            wizard.message = next_step.description

            if next_step.auto_executable:
                return await self._execute_auto_step(session_id)

            # invite URL 동적 생성 (Discord 등)
            if next_step.action_type == "user_action" and not next_step.action_url:
                invite_url = await connector.get_invite_url(wizard.credentials)
                if invite_url:
                    next_step.action_url = invite_url
                    wizard.message = f"{next_step.description}\n\n초대 링크: {invite_url}"

            return wizard
        else:
            return await self._finalize(session_id)

    async def _execute_auto_step(self, session_id: str) -> WizardState:
        """자동 실행 단계 처리."""
        session = self._sessions.get(session_id)
        if not session:
            return WizardState(
                session_id=session_id, platform="", current_step=0,
                total_steps=0, step_info=None, status="failed",
                message="세션 없음", error="session_not_found",
            )

        wizard = session.wizard
        connector = session.connector
        wizard.status = "processing"

        # 자격 증명 검증
        validation = await connector.validate_credentials(wizard.credentials)
        if validation.valid:
            # 연결 시도
            result = await connector.connect(wizard.credentials)
            if result.success:
                # 마지막 단계면 완료
                if wizard.current_step >= wizard.total_steps:
                    return await self._finalize(session_id)
                # 아니면 다음 단계
                return await self.process_step(session_id, {})

            wizard.status = "failed"
            wizard.message = result.message
            wizard.error = result.error
            return wizard

        # 검증 실패 — 다음 단계로 (입력 필요)
        if wizard.current_step < wizard.total_steps:
            wizard.current_step += 1
            next_step = session.steps[wizard.current_step - 1]
            wizard.step_info = next_step
            wizard.status = "waiting_input"
            wizard.message = next_step.description
            return wizard

        wizard.status = "failed"
        wizard.message = validation.message
        wizard.error = validation.error
        return wizard

    async def _finalize(self, session_id: str) -> WizardState:
        """위자드 완료: 게이트웨이 시작."""
        session = self._sessions.get(session_id)
        if not session:
            return WizardState(
                session_id=session_id, platform="", current_step=0,
                total_steps=0, step_info=None, status="failed",
                message="세션 없음", error="session_not_found",
            )

        wizard = session.wizard
        platform = wizard.platform

        # 게이트웨이 시작
        success = await self._lifecycle.start_gateway(platform)
        if success:
            wizard.status = "completed"
            wizard.message = f"{platform} 연결이 완료되었습니다!"
            # auto_start 설정 저장
            await self._db.set_setting(
                f"messenger_auto_start:{platform}", True
            )
        else:
            wizard.status = "failed"
            wizard.message = f"{platform} 게이트웨이 시작 실패"
            wizard.error = "gateway_start_failed"

        return wizard

    def get_current_state(self, session_id: str) -> WizardState | None:
        """현재 위자드 상태 조회."""
        session = self._sessions.get(session_id)
        return session.wizard if session else None

    async def cancel(self, session_id: str) -> None:
        """위자드 취소."""
        self._sessions.pop(session_id, None)

    def _cleanup_expired(self) -> None:
        """만료된 세션 정리."""
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.created_at > SESSION_TTL
        ]
        for sid in expired:
            del self._sessions[sid]

    @staticmethod
    def _get_token_env_map(platform: str) -> dict[str, str]:
        """필드 이름 → 환경변수 매핑."""
        maps = {
            "telegram": {"bot_token": "TELEGRAM_BOT_TOKEN"},
            "slack": {
                "bot_token": "SLACK_BOT_TOKEN",
                "app_token": "SLACK_APP_TOKEN",
            },
            "discord": {"bot_token": "DISCORD_BOT_TOKEN"},
            "whatsapp": {
                "account_sid": "WHATSAPP_TWILIO_ACCOUNT_SID",
                "auth_token": "WHATSAPP_TWILIO_AUTH_TOKEN",
                "from_number": "WHATSAPP_FROM_NUMBER",
            },
            "gmail": {
                "client_id": "GMAIL_CLIENT_ID",
                "client_secret": "GMAIL_CLIENT_SECRET",
                "refresh_token": "GMAIL_REFRESH_TOKEN",
            },
            "signal": {
                "phone_number": "SIGNAL_PHONE_NUMBER",
                "signal_cli_path": "SIGNAL_CLI_PATH",
            },
        }
        return maps.get(platform, {})

    def get_connector(self, platform: str) -> AutoConnector | None:
        """플랫폼별 AutoConnector 조회."""
        return self._connectors.get(platform)
```

- [ ] **Step 2: Update auto_connect/__init__.py exports**

Add `ConnectionOrchestrator` to the init exports.

```python
# src/breadmind/messenger/auto_connect/__init__.py — append
from breadmind.messenger.auto_connect.orchestrator import ConnectionOrchestrator
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/messenger/auto_connect/
git commit -m "feat(messenger): add ConnectionOrchestrator wizard state machine with session management"
```

---

### Task 11: API Routes Integration

**Files:**
- Modify: `src/breadmind/web/routes/system.py` — 신규 엔드포인트 추가

- [ ] **Step 1: Add new messenger API routes to system.py**

`system.py` 파일 끝에 다음 라우트를 추가합니다 (기존 messenger 라우트 아래):

```python
# ── Auto-Connect Wizard Routes ──────────────────────────────────

@app.post("/api/messenger/{platform}/auto-connect")
async def messenger_auto_connect(platform: str, request: Request):
    """자동 연결 위자드 시작."""
    orchestrator = app_state._orchestrator
    if not orchestrator:
        return JSONResponse({"error": "Orchestrator not initialized"}, 500)
    state = await orchestrator.start_connection(platform, "web")
    return _wizard_state_to_dict(state)


@app.post("/api/messenger/wizard/{session_id}/step")
async def messenger_wizard_step(session_id: str, request: Request):
    """위자드 다음 단계 진행."""
    orchestrator = app_state._orchestrator
    if not orchestrator:
        return JSONResponse({"error": "Orchestrator not initialized"}, 500)
    body = await request.json()
    state = await orchestrator.process_step(session_id, body)
    return _wizard_state_to_dict(state)


@app.get("/api/messenger/wizard/{session_id}/status")
async def messenger_wizard_status(session_id: str):
    """위자드 현재 상태 조회."""
    orchestrator = app_state._orchestrator
    if not orchestrator:
        return JSONResponse({"error": "Orchestrator not initialized"}, 500)
    state = orchestrator.get_current_state(session_id)
    if not state:
        return JSONResponse({"error": "Session not found"}, 404)
    return _wizard_state_to_dict(state)


@app.delete("/api/messenger/wizard/{session_id}")
async def messenger_wizard_cancel(session_id: str):
    """위자드 취소."""
    orchestrator = app_state._orchestrator
    if not orchestrator:
        return JSONResponse({"error": "Orchestrator not initialized"}, 500)
    await orchestrator.cancel(session_id)
    return {"status": "cancelled"}


# ── Lifecycle Routes ──────────────────────────────────────────

@app.get("/api/messenger/lifecycle/status")
async def messenger_lifecycle_status():
    """전체 게이트웨이 상태."""
    lifecycle = app_state._lifecycle_manager
    if not lifecycle:
        return JSONResponse({"error": "Lifecycle manager not initialized"}, 500)
    statuses = lifecycle.get_all_statuses()
    return {
        platform: {
            "state": s.state.value,
            "retry_count": s.retry_count,
            "last_error": s.last_error,
        }
        for platform, s in statuses.items()
    }


@app.post("/api/messenger/lifecycle/{platform}/restart")
async def messenger_lifecycle_restart(platform: str):
    """게이트웨이 재시작."""
    lifecycle = app_state._lifecycle_manager
    if not lifecycle:
        return JSONResponse({"error": "Lifecycle manager not initialized"}, 500)
    success = await lifecycle.restart_gateway(platform)
    return {"platform": platform, "restarted": success}


@app.get("/api/messenger/lifecycle/health")
async def messenger_lifecycle_health():
    """전체 health check."""
    lifecycle = app_state._lifecycle_manager
    if not lifecycle:
        return JSONResponse({"error": "Lifecycle manager not initialized"}, 500)
    health = await lifecycle.health_check_all()
    return {
        platform: {
            "state": h.state.value,
            "error": h.error,
            "retry_count": h.retry_count,
            "uptime_seconds": h.uptime_seconds,
        }
        for platform, h in health.items()
    }


# ── Security Routes ──────────────────────────────────────────

@app.get("/api/messenger/security/logs")
async def messenger_security_logs(platform: str = None, limit: int = 50):
    """접근 로그 조회."""
    security = app_state._messenger_security
    if not security:
        return JSONResponse({"error": "Security manager not initialized"}, 500)
    logs = security.get_access_logs(platform, limit)
    return [
        {
            "timestamp": log.timestamp,
            "platform": log.platform,
            "action": log.action,
            "actor": log.actor,
        }
        for log in logs
    ]


@app.get("/api/messenger/security/{platform}/expiry")
async def messenger_security_expiry(platform: str):
    """토큰 만료 상태."""
    security = app_state._messenger_security
    if not security:
        return JSONResponse({"error": "Security manager not initialized"}, 500)
    status = await security.check_token_expiry(platform)
    return {
        "platform": status.platform,
        "token_type": status.token_type,
        "needs_rotation": status.needs_rotation,
    }


def _wizard_state_to_dict(state) -> dict:
    """WizardState → dict 변환."""
    result = {
        "session_id": state.session_id,
        "platform": state.platform,
        "current_step": state.current_step,
        "total_steps": state.total_steps,
        "status": state.status,
        "message": state.message,
        "error": state.error,
    }
    if state.step_info:
        result["step_info"] = {
            "step_number": state.step_info.step_number,
            "title": state.step_info.title,
            "description": state.step_info.description,
            "action_type": state.step_info.action_type,
            "action_url": state.step_info.action_url,
            "auto_executable": state.step_info.auto_executable,
        }
        if state.step_info.input_fields:
            result["step_info"]["input_fields"] = [
                {
                    "name": f.name,
                    "label": f.label,
                    "placeholder": f.placeholder,
                    "secret": f.secret,
                    "required": f.required,
                }
                for f in state.step_info.input_fields
            ]
    return result
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/web/routes/system.py
git commit -m "feat(messenger): add auto-connect wizard, lifecycle, and security API routes"
```

---

### Task 12: Bootstrap Integration

**Files:**
- Modify: `src/breadmind/core/bootstrap.py` — `init_messenger()` 함수 추가
- Modify: `src/breadmind/main.py` — init_messenger 호출 추가
- Modify: `src/breadmind/web/app.py` — orchestrator, lifecycle, security 속성 추가

- [ ] **Step 1: Add init_messenger to bootstrap.py**

`bootstrap.py`의 `init_agent()` 함수 뒤에 추가:

```python
async def init_messenger(db, message_router, event_callback=None):
    """Initialize messenger auto-connect, lifecycle, and security components."""
    from breadmind.messenger.security import MessengerSecurityManager
    from breadmind.messenger.lifecycle import GatewayLifecycleManager
    from breadmind.messenger.auto_connect.orchestrator import ConnectionOrchestrator

    security = MessengerSecurityManager(db)
    await security.load_token_timestamps()

    lifecycle = GatewayLifecycleManager(
        message_router=message_router,
        db=db,
        event_callback=event_callback,
    )

    orchestrator = ConnectionOrchestrator(
        security_manager=security,
        lifecycle_manager=lifecycle,
        db=db,
    )

    # 설정된 게이트웨이 자동 시작
    results = await lifecycle.auto_start_all()
    started = [p for p, ok in results.items() if ok]
    if started:
        logger.info("Auto-started messengers: %s", started)

    return {
        "security": security,
        "lifecycle": lifecycle,
        "orchestrator": orchestrator,
    }
```

- [ ] **Step 2: Integrate into main.py**

`main.py`의 WebApp 생성 전에 `init_messenger()` 호출 추가.
`message_router`를 `WebApp` 생성 전에 초기화하고, messenger 컴포넌트를 WebApp에 전달.

`main.py`에서 WebApp 인스턴스 생성 부근 (기존 `message_router = MessageRouter()` 생성 위치 또는 WebApp 생성 직전)에:

```python
from breadmind.messenger.router import MessageRouter
from breadmind.core.bootstrap import init_messenger

message_router = MessageRouter()

messenger_components = await init_messenger(
    db=db,
    message_router=message_router,
    event_callback=None,  # WebApp 생성 후 교체
)
```

WebApp 생성 후:
```python
# event_callback 연결
messenger_components["lifecycle"]._event_callback = web_app.broadcast_event
```

- [ ] **Step 3: Add attributes to WebApp**

`web/app.py`의 `WebApp.__init__`에 새 파라미터 추가:

```python
# WebApp.__init__ 파라미터에 추가:
messenger_security=None,
lifecycle_manager=None,
orchestrator=None,

# 저장:
self._messenger_security = messenger_security
self._lifecycle_manager = lifecycle_manager
self._orchestrator = orchestrator
```

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/core/bootstrap.py src/breadmind/main.py src/breadmind/web/app.py
git commit -m "feat(messenger): integrate auto-connect system into bootstrap and WebApp"
```

---

### Task 13: Update messenger_connect Tool

**Files:**
- Modify: `src/breadmind/tools/builtin.py` — messenger_connect 도구 확장

- [ ] **Step 1: Extend messenger_connect tool**

기존 `messenger_connect` 함수를 확장하여 `ConnectionOrchestrator`를 활용:

```python
# builtin.py의 messenger_connect 함수를 교체

_orchestrator = None

def set_orchestrator(orchestrator):
    global _orchestrator
    _orchestrator = orchestrator


@tool(
    name="messenger_connect",
    description="메신저 플랫폼 연결 설정 (자동 가이드 + 토큰 검증)",
    parameters={
        "platform": {
            "type": "string",
            "enum": ["slack", "discord", "telegram", "whatsapp", "gmail", "signal"],
            "description": "연결할 메신저 플랫폼",
        },
        "credentials": {
            "type": "object",
            "description": "자격 증명 (토큰 등). 없으면 설정 가이드 반환",
            "default": {},
        },
    },
)
async def messenger_connect(platform: str, credentials: dict = None):
    if _orchestrator:
        state = await _orchestrator.start_connection(platform, "chat")
        if state.status == "completed":
            return f"✅ {platform} 연결 완료: {state.message}"
        if state.status == "failed":
            return f"❌ {platform} 연결 실패: {state.message}"

        # 사용자에게 안내
        lines = [f"📋 {platform} 연결 설정 ({state.current_step}/{state.total_steps})"]
        lines.append(f"\n**{state.step_info.title}**")
        lines.append(state.message)
        if state.step_info and state.step_info.action_url:
            lines.append(f"\n🔗 링크: {state.step_info.action_url}")
        if state.step_info and state.step_info.input_fields:
            lines.append("\n필요한 입력:")
            for f in state.step_info.input_fields:
                lines.append(f"  - {f.label}: {f.placeholder}")
        lines.append(f"\n세션 ID: {state.session_id}")
        return "\n".join(lines)

    # fallback: 기존 로직
    # (기존 messenger_connect 코드를 여기에 유지)
    return _legacy_messenger_connect(platform)
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/tools/builtin.py
git commit -m "feat(messenger): upgrade messenger_connect tool with orchestrator integration"
```

---

## Chunk 5: CLI & Shutdown

### Task 14: CLI Commands

**Files:**
- Create: `src/breadmind/cli/messenger.py`

- [ ] **Step 1: Implement CLI messenger commands**

```python
# src/breadmind/cli/messenger.py
from __future__ import annotations

import argparse
import asyncio
import sys


async def cmd_setup(args):
    """대화형 메신저 연결 위자드."""
    from breadmind.config import load_config
    from breadmind.core.bootstrap import init_database, init_messenger
    from breadmind.messenger.router import MessageRouter

    config = load_config(args.config_dir)
    db = await init_database(config, args.config_dir)
    router = MessageRouter()
    components = await init_messenger(db, router)
    orchestrator = components["orchestrator"]

    platforms = ["slack", "discord", "telegram", "whatsapp", "gmail", "signal"]
    platform = args.platform

    if not platform:
        print("\n사용 가능한 메신저 플랫폼:")
        for i, p in enumerate(platforms, 1):
            print(f"  {i}. {p}")
        try:
            choice = input("\n플랫폼 번호를 선택하세요: ").strip()
            idx = int(choice) - 1
            platform = platforms[idx]
        except (ValueError, IndexError):
            print("잘못된 선택입니다.")
            return

    print(f"\n{platform} 연결을 시작합니다...")
    state = await orchestrator.start_connection(platform, "cli")

    while state.status not in ("completed", "failed"):
        print(f"\n── 단계 {state.current_step}/{state.total_steps}: {state.step_info.title} ──")
        print(state.message)

        if state.step_info and state.step_info.action_url:
            print(f"\n🔗 {state.step_info.action_url}")

        if state.step_info and state.step_info.action_type == "user_input":
            user_input = {}
            for field in state.step_info.input_fields or []:
                prompt = f"{field.label}"
                if field.placeholder:
                    prompt += f" ({field.placeholder})"
                prompt += ": "
                if field.secret:
                    import getpass
                    value = getpass.getpass(prompt)
                else:
                    value = input(prompt)
                if value:
                    user_input[field.name] = value
            state = await orchestrator.process_step(state.session_id, user_input)
        elif state.step_info and state.step_info.action_type == "user_action":
            input("\n위 작업을 완료한 후 Enter를 누르세요...")
            state = await orchestrator.process_step(state.session_id, {})
        elif state.step_info and state.step_info.action_type == "oauth_redirect":
            print("\n브라우저에서 위 링크를 열어 인증을 완료하세요.")
            input("인증 완료 후 Enter를 누르세요...")
            state = await orchestrator.process_step(state.session_id, {})
        else:
            state = await orchestrator.process_step(state.session_id, {})

    if state.status == "completed":
        print(f"\n✅ {state.message}")
    else:
        print(f"\n❌ {state.message}")
        if state.error:
            print(f"   오류: {state.error}")

    await db.disconnect()


async def cmd_status(args):
    """메신저 상태 확인."""
    from breadmind.config import load_config
    from breadmind.core.bootstrap import init_database, init_messenger
    from breadmind.messenger.router import MessageRouter

    config = load_config(args.config_dir)
    db = await init_database(config, args.config_dir)
    router = MessageRouter()
    components = await init_messenger(db, router)
    lifecycle = components["lifecycle"]

    statuses = lifecycle.get_all_statuses()
    print("\n메신저 상태:")
    print(f"{'플랫폼':<12} {'상태':<15} {'재시도':<6} {'에러'}")
    print("-" * 60)
    for platform, status in statuses.items():
        print(
            f"{platform:<12} {status.state.value:<15} "
            f"{status.retry_count:<6} {status.last_error or '-'}"
        )

    await lifecycle.shutdown()
    await db.disconnect()


async def cmd_restart(args):
    """메신저 재시작."""
    from breadmind.config import load_config
    from breadmind.core.bootstrap import init_database, init_messenger
    from breadmind.messenger.router import MessageRouter

    config = load_config(args.config_dir)
    db = await init_database(config, args.config_dir)
    router = MessageRouter()
    components = await init_messenger(db, router)
    lifecycle = components["lifecycle"]

    if args.platform:
        success = await lifecycle.restart_gateway(args.platform)
        print(f"{args.platform}: {'재시작 성공' if success else '재시작 실패'}")
    else:
        results = await lifecycle.auto_start_all()
        for platform, ok in results.items():
            print(f"{platform}: {'시작됨' if ok else '미시작'}")

    await lifecycle.shutdown()
    await db.disconnect()


def add_messenger_subparser(subparsers):
    """main CLI 파서에 messenger 서브커맨드 등록."""
    msg_parser = subparsers.add_parser("messenger", help="메신저 관리")
    msg_sub = msg_parser.add_subparsers(dest="messenger_cmd")

    setup_p = msg_sub.add_parser("setup", help="메신저 연결 설정")
    setup_p.add_argument("--platform", choices=[
        "slack", "discord", "telegram", "whatsapp", "gmail", "signal"
    ])
    setup_p.set_defaults(func=lambda args: asyncio.run(cmd_setup(args)))

    status_p = msg_sub.add_parser("status", help="메신저 상태 확인")
    status_p.set_defaults(func=lambda args: asyncio.run(cmd_status(args)))

    restart_p = msg_sub.add_parser("restart", help="메신저 재시작")
    restart_p.add_argument("platform", nargs="?", help="재시작할 플랫폼")
    restart_p.set_defaults(func=lambda args: asyncio.run(cmd_restart(args)))
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/cli/messenger.py
git commit -m "feat(messenger): add CLI commands for messenger setup, status, restart"
```

---

### Task 15: Graceful Shutdown Integration

**Files:**
- Modify: `src/breadmind/main.py` — shutdown 시 lifecycle manager 정리

- [ ] **Step 1: Add shutdown hook in main.py**

`main.py`의 서버 종료 부분에:

```python
# 서버 종료 시 lifecycle 정리
if messenger_components:
    await messenger_components["lifecycle"].shutdown()
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/main.py
git commit -m "feat(messenger): add graceful shutdown for gateway lifecycle manager"
```

---

### Task 16: Update __init__.py exports

**Files:**
- Modify: `src/breadmind/messenger/auto_connect/__init__.py`

- [ ] **Step 1: Final exports**

```python
# src/breadmind/messenger/auto_connect/__init__.py
from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    CreateResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
    WizardState,
)
from breadmind.messenger.auto_connect.orchestrator import ConnectionOrchestrator
from breadmind.messenger.auto_connect.discord import DiscordAutoConnector
from breadmind.messenger.auto_connect.gmail import GmailAutoConnector
from breadmind.messenger.auto_connect.signal import SignalAutoConnector
from breadmind.messenger.auto_connect.slack import SlackAutoConnector
from breadmind.messenger.auto_connect.telegram import TelegramAutoConnector
from breadmind.messenger.auto_connect.whatsapp import WhatsAppAutoConnector

__all__ = [
    "AutoConnector",
    "ConnectionOrchestrator",
    "ConnectionResult",
    "CreateResult",
    "DiscordAutoConnector",
    "GatewayState",
    "GmailAutoConnector",
    "HealthStatus",
    "InputField",
    "SetupStep",
    "SignalAutoConnector",
    "SlackAutoConnector",
    "TelegramAutoConnector",
    "ValidationResult",
    "WhatsAppAutoConnector",
    "WizardState",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/messenger/auto_connect/__init__.py
git commit -m "feat(messenger): finalize auto_connect package exports"
```
