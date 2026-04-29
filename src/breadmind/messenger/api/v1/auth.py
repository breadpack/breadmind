"""HTTP authentication endpoints for the messenger v1 API.

Bridges the auth primitives in :mod:`breadmind.messenger.auth` to FastAPI
routes so HTTP clients can:

  * ``POST /auth/signup`` — bootstrap the very first user of a workspace
    (no token required, single-use per slug).
  * ``POST /auth/otp/request`` — request a 6-digit email OTP.
  * ``POST /auth/otp/verify`` — exchange a valid OTP for access+refresh.
  * ``POST /auth/refresh`` — rotate a refresh token.

These routes are NOT gated by ``Depends(get_current_user)`` — they are
the only legitimate entry points for tokenless clients.

The router carries no extra prefix; it is mounted onto the messenger v1
router (which itself is prefixed ``/api`` and exposed via the versioning
middleware as ``/api/v1/...``). Final paths are therefore
``/api/v1/auth/...``.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field

from breadmind.messenger.api.v1.deps import get_db
from breadmind.messenger.auth.email_otp import (
    OtpExpired,
    OtpInvalid,
    SmtpClient,
    request_otp,
    verify_otp,
)
from breadmind.messenger.auth.session import (
    RefreshTokenInvalid,
    SessionRevoked,
    create_session,
    refresh_session,
)
from breadmind.messenger.errors import (
    Conflict,
    NotFound,
    Unauthorized,
    ValidationFailed,
)
from breadmind.messenger.service.workspace_service import create_workspace

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_TRUTHY = {"true", "1", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _access_ttl_min() -> int:
    return _env_int("BREADMIND_MESSENGER_SESSION_ACCESS_TTL_MIN", 30)


def _refresh_ttl_days() -> int:
    return _env_int("BREADMIND_MESSENGER_SESSION_REFRESH_TTL_DAYS", 30)


def _otp_ttl_min() -> int:
    return _env_int("BREADMIND_MESSENGER_OTP_TTL_MIN", 10)


def _otp_max_attempts() -> int:
    return _env_int("BREADMIND_MESSENGER_OTP_MAX_ATTEMPTS", 5)


def _smtp_stub_enabled() -> bool:
    """When True, OTPs are logged at INFO instead of being mailed.

    Intended for canary / dev. Production must leave this unset (or
    ``false``) and configure a real SMTP relay.
    """
    return _env_bool("BREADMIND_MESSENGER_OTP_STUB", default=False)


def _smtp_stub_returns_code() -> bool:
    """Diagnostic mode — when True the OTP request response includes the
    plaintext code so canary scripts can complete the flow without a
    real mailbox. Implies ``_smtp_stub_enabled``.
    """
    return _env_bool("BREADMIND_MESSENGER_OTP_RETURN_CODE", default=False)


class _StubSmtp:
    """SmtpClient that logs at INFO instead of dispatching.

    The plaintext code is captured by the route handler before this
    client sees it, so the log line can safely include a redacted
    fingerprint without leaking the secret to operators tailing logs.
    """

    def send(self, *, to: str, subject: str, body: str) -> None:  # noqa: D401
        logger.info(
            "STUB SMTP send: to=%s subject=%s body_len=%d",
            to,
            subject,
            len(body),
        )


def _smtp_client_for(request: Request) -> SmtpClient:
    """Return the SmtpClient FastAPI route handlers should use.

    Test harnesses can override by setting ``request.app.state.smtp_client``;
    canary/dev gets the stub when the env flag is on; otherwise we raise so
    a misconfigured production deploy fails loudly rather than silently
    accepting OTP requests it can't deliver.
    """
    override = getattr(request.app.state, "smtp_client", None)
    if override is not None:
        return override
    if _smtp_stub_enabled() or _smtp_stub_returns_code():
        return _StubSmtp()
    raise Unauthorized(
        "smtp client not configured; set BREADMIND_MESSENGER_OTP_STUB=true "
        "for canary/dev or wire app.state.smtp_client in production"
    )


def _paseto_key(request: Request) -> str:
    key = getattr(request.app.state, "paseto_key_hex", None)
    if not key:
        raise Unauthorized(
            "PASETO key not configured; set BREADMIND_MESSENGER_PASETO_KEY_HEX"
        )
    return key


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    workspace_slug: str = Field(min_length=2, max_length=64)
    workspace_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)


class OtpRequestBody(BaseModel):
    email: EmailStr
    workspace_slug: str = Field(min_length=2, max_length=64)


class OtpVerifyBody(BaseModel):
    email: EmailStr
    workspace_slug: str = Field(min_length=2, max_length=64)
    code: str = Field(min_length=4, max_length=12)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=10)


class SessionResponse(BaseModel):
    user_id: UUID
    workspace_id: UUID
    session_id: UUID
    access_token: str
    refresh_token: str
    access_ttl_min: int
    refresh_ttl_days: int


class OtpRequestResponse(BaseModel):
    status: str = "sent"
    # Populated only when BREADMIND_MESSENGER_OTP_RETURN_CODE=true.
    debug_code: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
) -> SessionResponse:
    """Bootstrap the first user of a brand-new workspace.

    The workspace slug must be unused; this endpoint cannot be used to
    inject extra owners into an existing workspace (that path requires
    an authenticated invite). The created user gets ``role='owner'`` and
    receives a fresh access+refresh pair.
    """
    if not _SLUG_RE.match(body.workspace_slug):
        raise ValidationFailed([
            {"field": "workspace_slug", "msg": "lowercase alnum + hyphen, 4-64 chars"},
        ])
    key = _paseto_key(request)

    async with db.transaction():
        existing = await db.fetchval(
            "SELECT id FROM org_projects WHERE slug = $1",
            body.workspace_slug,
        )
        if existing is not None:
            raise Conflict(
                f"workspace slug '{body.workspace_slug}' is taken; "
                "use an invite to join an existing workspace",
            )

        ws = await create_workspace(
            db,
            name=body.workspace_name,
            slug=body.workspace_slug,
            created_by=None,
        )

        uid = uuid4()
        await db.execute(
            """INSERT INTO workspace_users
                  (id, workspace_id, email, kind, display_name, role)
               VALUES ($1, $2, $3, 'human', $4, 'owner')""",
            uid,
            ws.id,
            body.email,
            body.display_name,
        )

        tokens = await create_session(
            db,
            key,
            user_id=uid,
            workspace_id=ws.id,
            access_ttl_min=_access_ttl_min(),
            refresh_ttl_days=_refresh_ttl_days(),
            ip=request.client.host if request.client else None,
        )

    return SessionResponse(
        user_id=uid,
        workspace_id=ws.id,
        session_id=tokens.session_id,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_ttl_min=_access_ttl_min(),
        refresh_ttl_days=_refresh_ttl_days(),
    )


@router.post(
    "/otp/request",
    response_model=OtpRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_otp_request(
    body: OtpRequestBody,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
) -> OtpRequestResponse:
    """Issue a one-time login code to ``body.email``.

    Returns ``202`` even when the user/workspace pair does not exist so
    we never confirm an account's existence to anonymous callers. When
    ``BREADMIND_MESSENGER_OTP_RETURN_CODE=true`` (canary diagnostic
    mode) the response also carries the plaintext code.
    """
    user_row = await db.fetchrow(
        """SELECT wu.id
             FROM workspace_users wu
             JOIN org_projects op ON op.id = wu.workspace_id
            WHERE wu.email = $1 AND op.slug = $2 AND wu.deactivated_at IS NULL""",
        body.email,
        body.workspace_slug,
    )
    if user_row is None:
        # Don't leak existence — pretend we sent.
        logger.info(
            "otp request for unknown email/slug pair (slug=%s)",
            body.workspace_slug,
        )
        return OtpRequestResponse()

    smtp = _smtp_client_for(request)
    code = await request_otp(
        db,
        smtp,
        email=body.email,
        workspace_slug=body.workspace_slug,
        ttl_min=_otp_ttl_min(),
    )
    debug_code = code if _smtp_stub_returns_code() else None
    return OtpRequestResponse(debug_code=debug_code)


@router.post("/otp/verify", response_model=SessionResponse)
async def post_otp_verify(
    body: OtpVerifyBody,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
) -> SessionResponse:
    """Exchange an OTP for a fresh access+refresh pair."""
    key = _paseto_key(request)
    user_row = await db.fetchrow(
        """SELECT wu.id, wu.workspace_id
             FROM workspace_users wu
             JOIN org_projects op ON op.id = wu.workspace_id
            WHERE wu.email = $1 AND op.slug = $2 AND wu.deactivated_at IS NULL""",
        body.email,
        body.workspace_slug,
    )
    if user_row is None:
        raise Unauthorized("invalid email or workspace")

    try:
        await verify_otp(
            db,
            email=body.email,
            workspace_slug=body.workspace_slug,
            code=body.code,
            max_attempts=_otp_max_attempts(),
        )
    except (OtpInvalid, OtpExpired) as e:
        raise Unauthorized(str(e)) from e

    tokens = await create_session(
        db,
        key,
        user_id=user_row["id"],
        workspace_id=user_row["workspace_id"],
        access_ttl_min=_access_ttl_min(),
        refresh_ttl_days=_refresh_ttl_days(),
        ip=request.client.host if request.client else None,
    )
    return SessionResponse(
        user_id=user_row["id"],
        workspace_id=user_row["workspace_id"],
        session_id=tokens.session_id,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_ttl_min=_access_ttl_min(),
        refresh_ttl_days=_refresh_ttl_days(),
    )


@router.post("/refresh", response_model=SessionResponse)
async def post_refresh(
    body: RefreshBody,
    request: Request,
    db: asyncpg.Connection = Depends(get_db),
) -> SessionResponse:
    """Rotate a refresh token, invalidating the previous one."""
    key = _paseto_key(request)
    try:
        tokens = await refresh_session(
            db,
            key,
            refresh_token=body.refresh_token,
            access_ttl_min=_access_ttl_min(),
            refresh_ttl_days=_refresh_ttl_days(),
        )
    except (RefreshTokenInvalid, SessionRevoked) as e:
        raise Unauthorized(str(e)) from e

    row = await db.fetchrow(
        "SELECT user_id, workspace_id FROM user_sessions WHERE id = $1",
        tokens.session_id,
    )
    if row is None:
        raise Unauthorized("session vanished after rotation")

    return SessionResponse(
        user_id=row["user_id"],
        workspace_id=row["workspace_id"],
        session_id=tokens.session_id,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        access_ttl_min=_access_ttl_min(),
        refresh_ttl_days=_refresh_ttl_days(),
    )
