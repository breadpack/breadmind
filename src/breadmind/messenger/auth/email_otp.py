"""Email-based OTP for sign-in (6-digit code, 10min TTL, 5 attempts max)."""
from __future__ import annotations
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from typing import Protocol


_OTP_LEN = 6
_HMAC_KEY = b"breadmind-otp-salt-v1"


class OtpInvalid(Exception):
    pass


class OtpExpired(Exception):
    pass


class SmtpClient(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


def generate_code() -> str:
    return f"{secrets.randbelow(10 ** _OTP_LEN):0{_OTP_LEN}d}"


def hash_code(code: str, email: str) -> bytes:
    """HMAC-SHA256 of (email || \\0 || code) using fixed salt."""
    msg = email.encode() + b"\0" + code.encode()
    return hmac.new(_HMAC_KEY, msg, hashlib.sha256).digest()


async def request_otp(
    db,
    smtp: SmtpClient,
    *,
    email: str,
    workspace_slug: str,
    ttl_min: int,
) -> str:
    """Generate, store, and send an OTP. Returns the plaintext code (caller should not log)."""
    code = generate_code()
    code_hash = hash_code(code, email)
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl_min)
    await db.execute(
        """INSERT INTO email_otp (email, workspace_slug, code_hash, expires_at, attempts)
           VALUES ($1, $2, $3, $4, 0)
           ON CONFLICT (email, workspace_slug) DO UPDATE
           SET code_hash = EXCLUDED.code_hash,
               expires_at = EXCLUDED.expires_at,
               attempts = 0,
               used_at = NULL""",
        email, workspace_slug or "", code_hash, expires,
    )
    smtp.send(
        to=email,
        subject="BreadMind 로그인 코드",
        body=f"인증 코드: {code}\n10분 안에 사용해주세요.",
    )
    return code


async def verify_otp(
    db,
    *,
    email: str,
    workspace_slug: str,
    code: str,
    max_attempts: int = 5,
) -> None:
    row = await db.fetchrow(
        """SELECT code_hash, expires_at, used_at, attempts
           FROM email_otp WHERE email = $1 AND workspace_slug = $2""",
        email, workspace_slug or "",
    )
    if row is None:
        raise OtpInvalid("no otp issued")
    if row["used_at"] is not None:
        raise OtpInvalid("already used")
    if row["attempts"] >= max_attempts:
        raise OtpInvalid("max attempts exceeded")
    if datetime.now(timezone.utc) > row["expires_at"]:
        raise OtpExpired("expired")
    expected = hash_code(code, email)
    if not hmac.compare_digest(expected, row["code_hash"]):
        await db.execute(
            "UPDATE email_otp SET attempts = attempts + 1 "
            "WHERE email = $1 AND workspace_slug = $2", email, workspace_slug or "",
        )
        raise OtpInvalid("code mismatch")
    await db.execute(
        "UPDATE email_otp SET used_at = now() WHERE email = $1 AND workspace_slug = $2",
        email, workspace_slug or "",
    )
