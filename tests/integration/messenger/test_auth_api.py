"""HTTP auth endpoints — signup / OTP request / OTP verify / refresh.

Closes the bootstrap gap that the M2 deps canary exposed (B4 + B6):
without these routes a freshly deployed messenger service has no
HTTP-callable path that issues a PASETO access token, so no client can
ever reach the workspace/channel APIs.
"""
from __future__ import annotations

from uuid import uuid4

import pytest_asyncio


@pytest_asyncio.fixture
async def auth_app(messenger_app, fake_smtp):
    """messenger_app + smtp override so the OTP routes are deterministic."""
    messenger_app.state.smtp_client = fake_smtp
    return messenger_app


@pytest_asyncio.fixture
async def auth_client(auth_app):
    import httpx
    from httpx import ASGITransport

    async with httpx.AsyncClient(
        transport=ASGITransport(app=auth_app),
        base_url="http://test",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# /auth/signup
# ---------------------------------------------------------------------------


async def test_signup_creates_workspace_user_and_session(auth_client, test_db):
    slug = f"sg-{uuid4().hex[:8]}"
    r = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"owner-{uuid4().hex[:6]}@x.com",
            "workspace_slug": slug,
            "workspace_name": "Acme",
            "display_name": "Owner",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user_id"]
    assert body["workspace_id"]

    ws_count = await test_db.fetchval(
        "SELECT count(*) FROM org_projects WHERE slug = $1", slug
    )
    assert ws_count == 1
    user_role = await test_db.fetchval(
        "SELECT role FROM workspace_users WHERE id = $1", body["user_id"]
    )
    assert user_role == "owner"


async def test_signup_rejects_duplicate_slug(auth_client):
    slug = f"dup-{uuid4().hex[:8]}"
    payload = {
        "workspace_slug": slug,
        "workspace_name": "First",
        "display_name": "First Owner",
    }
    first = await auth_client.post(
        "/api/v1/auth/signup",
        json={**payload, "email": f"first-{uuid4().hex[:6]}@x.com"},
    )
    assert first.status_code == 201, first.text

    second = await auth_client.post(
        "/api/v1/auth/signup",
        json={**payload, "email": f"second-{uuid4().hex[:6]}@x.com"},
    )
    assert second.status_code == 409, second.text


async def test_signup_rejects_invalid_slug(auth_client):
    r = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"x-{uuid4().hex[:6]}@x.com",
            "workspace_slug": "BadSlug!",
            "workspace_name": "X",
            "display_name": "X",
        },
    )
    # 422 from pydantic OR our explicit ValidationFailed (also 422)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# /auth/otp/request + /auth/otp/verify
# ---------------------------------------------------------------------------


async def test_otp_request_sends_for_known_user(auth_client, fake_smtp, test_db):
    slug = f"otp-{uuid4().hex[:8]}"
    email = f"u-{uuid4().hex[:6]}@x.com"
    signup = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "workspace_slug": slug,
            "workspace_name": "X",
            "display_name": "U",
        },
    )
    assert signup.status_code == 201

    r = await auth_client.post(
        "/api/v1/auth/otp/request",
        json={"email": email, "workspace_slug": slug},
    )
    assert r.status_code == 202, r.text
    assert any(m["to"] == email for m in fake_smtp.sent)


async def test_otp_request_silent_for_unknown(auth_client, fake_smtp):
    r = await auth_client.post(
        "/api/v1/auth/otp/request",
        json={
            "email": f"ghost-{uuid4().hex[:6]}@example.com",
            "workspace_slug": f"nope-{uuid4().hex[:8]}",
        },
    )
    # Don't leak existence — same 202 as the happy path.
    assert r.status_code == 202, r.text
    assert not fake_smtp.sent


async def test_otp_verify_returns_tokens(auth_client, fake_smtp, test_db):
    slug = f"otpv-{uuid4().hex[:8]}"
    email = f"v-{uuid4().hex[:6]}@x.com"
    await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "workspace_slug": slug,
            "workspace_name": "X",
            "display_name": "V",
        },
    )
    await auth_client.post(
        "/api/v1/auth/otp/request",
        json={"email": email, "workspace_slug": slug},
    )
    # Pull the plaintext code straight from the captured email body.
    sent = [m for m in fake_smtp.sent if m["to"] == email][-1]
    code = next(
        token for token in sent["body"].split() if token.isdigit() and len(token) == 6
    )

    r = await auth_client.post(
        "/api/v1/auth/otp/verify",
        json={"email": email, "workspace_slug": slug, "code": code},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_otp_verify_rejects_wrong_code(auth_client, fake_smtp):
    slug = f"otpw-{uuid4().hex[:8]}"
    email = f"w-{uuid4().hex[:6]}@x.com"
    await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "workspace_slug": slug,
            "workspace_name": "X",
            "display_name": "W",
        },
    )
    await auth_client.post(
        "/api/v1/auth/otp/request",
        json={"email": email, "workspace_slug": slug},
    )

    r = await auth_client.post(
        "/api/v1/auth/otp/verify",
        json={"email": email, "workspace_slug": slug, "code": "000000"},
    )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# /auth/refresh
# ---------------------------------------------------------------------------


async def test_refresh_rotates_token(auth_client):
    slug = f"rf-{uuid4().hex[:8]}"
    signup = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"r-{uuid4().hex[:6]}@x.com",
            "workspace_slug": slug,
            "workspace_name": "X",
            "display_name": "R",
        },
    )
    refresh_token = signup.json()["refresh_token"]

    r = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"] != refresh_token, (
        "rotation must produce a new refresh token"
    )

    # Old token must now be unusable.
    second = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert second.status_code == 401, second.text


async def test_refresh_rejects_garbage(auth_client):
    r = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "v4.local.notarealtoken"},
    )
    assert r.status_code == 401, r.text
