import pytest
from uuid import uuid4
from breadmind.messenger.auth.invite import (
    create_invite, accept_invite, revoke_invite, InviteInvalid, InviteExpired,
)


async def test_create_and_accept(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    suffix = uuid4().hex[:8]
    email = f"bob-{suffix}@x.com"
    invite = await create_invite(
        test_db, workspace_id=wid, email=email,
        invited_by=owner_id, role="member", ttl_days=14,
    )
    new_user_id = await accept_invite(
        test_db, token=invite.token, display_name="Bob", external_id=None,
    )
    row = await test_db.fetchrow(
        "SELECT email, role FROM workspace_users WHERE id = $1", new_user_id,
    )
    assert row["email"] == email
    assert row["role"] == "member"


async def test_accept_expired_raises(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    suffix = uuid4().hex[:8]
    email = f"bob-{suffix}@x.com"
    invite = await create_invite(
        test_db, workspace_id=wid, email=email,
        invited_by=owner_id, role="member", ttl_days=-1,
    )
    with pytest.raises(InviteExpired):
        await accept_invite(test_db, token=invite.token, display_name="Bob")


async def test_accept_revoked_raises(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    suffix = uuid4().hex[:8]
    email = f"bob-{suffix}@x.com"
    invite = await create_invite(
        test_db, workspace_id=wid, email=email,
        invited_by=owner_id, role="member", ttl_days=14,
    )
    await revoke_invite(test_db, invite.id)
    with pytest.raises(InviteInvalid):
        await accept_invite(test_db, token=invite.token, display_name="Bob")


async def test_accept_twice_raises(test_db, seed_workspace):
    wid, owner_id = seed_workspace
    suffix = uuid4().hex[:8]
    email = f"bob-{suffix}@x.com"
    invite = await create_invite(
        test_db, workspace_id=wid, email=email,
        invited_by=owner_id, role="member", ttl_days=14,
    )
    await accept_invite(test_db, token=invite.token, display_name="Bob")
    with pytest.raises(InviteInvalid):
        await accept_invite(test_db, token=invite.token, display_name="Bob2")
