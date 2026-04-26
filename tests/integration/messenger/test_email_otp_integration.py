import pytest
from uuid import uuid4
from breadmind.messenger.auth.email_otp import (
    request_otp, verify_otp, OtpInvalid, OtpExpired,
)


@pytest.mark.asyncio
async def test_request_then_verify_success(test_db, fake_smtp):
    suffix = uuid4().hex[:8]
    email = f"alice-{suffix}@acme.com"
    slug = f"acme-{suffix}"
    code = await request_otp(
        test_db, fake_smtp, email=email, workspace_slug=slug, ttl_min=10,
    )
    await verify_otp(test_db, email=email, workspace_slug=slug, code=code)


@pytest.mark.asyncio
async def test_verify_wrong_code_raises(test_db, fake_smtp):
    suffix = uuid4().hex[:8]
    email = f"alice-{suffix}@acme.com"
    slug = f"acme-{suffix}"
    await request_otp(test_db, fake_smtp, email=email, workspace_slug=slug, ttl_min=10)
    with pytest.raises(OtpInvalid):
        await verify_otp(test_db, email=email, workspace_slug=slug, code="000000")


@pytest.mark.asyncio
async def test_verify_after_expiry_raises(test_db, fake_smtp):
    suffix = uuid4().hex[:8]
    email = f"alice-{suffix}@acme.com"
    slug = f"acme-{suffix}"
    code = await request_otp(test_db, fake_smtp, email=email, workspace_slug=slug, ttl_min=-1)
    with pytest.raises(OtpExpired):
        await verify_otp(test_db, email=email, workspace_slug=slug, code=code)


@pytest.mark.asyncio
async def test_verify_consumes_otp(test_db, fake_smtp):
    suffix = uuid4().hex[:8]
    email = f"alice-{suffix}@acme.com"
    slug = f"acme-{suffix}"
    code = await request_otp(test_db, fake_smtp, email=email, workspace_slug=slug, ttl_min=10)
    await verify_otp(test_db, email=email, workspace_slug=slug, code=code)
    with pytest.raises(OtpInvalid):
        await verify_otp(test_db, email=email, workspace_slug=slug, code=code)
