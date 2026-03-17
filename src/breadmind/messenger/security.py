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
