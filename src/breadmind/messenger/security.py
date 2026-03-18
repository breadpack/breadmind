from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from breadmind.messenger.platforms import get_token_env_map

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

    ROTATION_THRESHOLD_DAYS = 90

    def __init__(self, db, vault=None):
        self._db = db
        self._vault = vault
        self._access_logs: list[AccessLog] = []
        self._token_timestamps: dict[str, float] = {}

    async def store_token(
        self, platform: str, key: str, value: str, actor: str = "system"
    ) -> None:
        """토큰을 암호화하여 Vault에 저장하고 접근 로그 기록."""
        import os

        os.environ[key] = value

        if self._vault:
            await self._vault.store(
                f"messenger:{platform}:{key}", value,
                metadata={"platform": platform, "key": key},
            )
        else:
            # Fallback: legacy unencrypted storage
            await self._db.set_setting(
                f"messenger_token:{key}",
                {"value": value, "stored_at": time.time()},
            )

        self._token_timestamps[f"{platform}:{key}"] = time.time()
        self._log_access(platform, "write", actor)
        logger.info("Token stored for %s:%s", platform, self.mask_token(value))

    async def get_token(
        self, platform: str, key: str, actor: str = "system"
    ) -> str | None:
        """Vault(암호화) 또는 DB에서 토큰 조회."""
        import os

        value = os.environ.get(key)
        if not value and self._vault:
            value = await self._vault.retrieve(f"messenger:{platform}:{key}")
        if not value:
            # Fallback: legacy unencrypted format
            result = await self._db.get_setting(f"messenger_token:{key}")
            if result and isinstance(result, dict):
                value = result.get("value")
                # Auto-migrate to vault on read
                if value and self._vault:
                    await self._vault.store(
                        f"messenger:{platform}:{key}", value,
                        metadata={"platform": platform, "key": key},
                    )
        if value:
            self._log_access(platform, "read", actor)
        return value

    async def delete_token(
        self, platform: str, key: str, actor: str = "system"
    ) -> None:
        """토큰 삭제 (Vault + legacy)."""
        import os

        os.environ.pop(key, None)
        if self._vault:
            await self._vault.delete(f"messenger:{platform}:{key}")
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
        keys = get_token_env_map().get(platform, [])
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
        for platform, keys in get_token_env_map().items():
            for key in keys:
                result = await self._db.get_setting(f"messenger_token:{key}")
                if result:
                    ts = result.get("stored_at", time.time())
                    self._token_timestamps[f"{platform}:{key}"] = ts
