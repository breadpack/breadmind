from __future__ import annotations
import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True, slots=True)
class MessengerConfig:
    paseto_key_hex: str
    session_access_ttl_min: int
    session_refresh_ttl_days: int
    invite_ttl_days: int
    visible_channels_ttl_sec: int
    rate_limit_tier1: int
    rate_limit_tier2: int
    rate_limit_tier3: int
    otp_smtp_url: str
    otp_from: str
    otp_ttl_min: int
    otp_max_attempts: int
    file_backend: str
    file_fs_root: str
    fanout_backend: str

    @classmethod
    def from_env(cls) -> "MessengerConfig":
        return cls(
            paseto_key_hex=_env_str("BREADMIND_MESSENGER_PASETO_KEY_HEX", "0" * 64),
            session_access_ttl_min=_env_int("BREADMIND_MESSENGER_SESSION_ACCESS_TTL_MIN", 30),
            session_refresh_ttl_days=_env_int("BREADMIND_MESSENGER_SESSION_REFRESH_TTL_DAYS", 30),
            invite_ttl_days=_env_int("BREADMIND_MESSENGER_INVITE_TTL_DAYS", 14),
            visible_channels_ttl_sec=_env_int("BREADMIND_MESSENGER_VISIBLE_CHANNELS_TTL_SEC", 300),
            rate_limit_tier1=_env_int("BREADMIND_MESSENGER_RATE_LIMIT_TIER1", 1),
            rate_limit_tier2=_env_int("BREADMIND_MESSENGER_RATE_LIMIT_TIER2", 50),
            rate_limit_tier3=_env_int("BREADMIND_MESSENGER_RATE_LIMIT_TIER3", 500),
            otp_smtp_url=_env_str("BREADMIND_MESSENGER_OTP_SMTP_URL", "smtp://localhost:25"),
            otp_from=_env_str("BREADMIND_MESSENGER_OTP_FROM", "noreply@breadmind.local"),
            otp_ttl_min=_env_int("BREADMIND_MESSENGER_OTP_TTL_MIN", 10),
            otp_max_attempts=_env_int("BREADMIND_MESSENGER_OTP_MAX_ATTEMPTS", 5),
            file_backend=_env_str("BREADMIND_MESSENGER_FILE_BACKEND", "fs"),
            file_fs_root=_env_str("BREADMIND_MESSENGER_FILE_FS_ROOT", "/var/lib/breadmind/files"),
            fanout_backend=_env_str("BREADMIND_MESSENGER_FANOUT_BACKEND", "pg_notify"),
        )
