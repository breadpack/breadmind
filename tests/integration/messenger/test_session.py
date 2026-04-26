import pytest
from breadmind.messenger.auth.session import (
    create_session, refresh_session, revoke_session, SessionRevoked, RefreshTokenInvalid,
)

KEY = "00" * 32


async def test_create_session_returns_tokens(test_db, seed_workspace):
    wid, uid = seed_workspace
    sess = await create_session(
        test_db, KEY, user_id=uid, workspace_id=wid,
        access_ttl_min=30, refresh_ttl_days=30,
        device_info={"ua": "test"}, ip="1.2.3.4",
    )
    assert sess.access_token
    assert sess.refresh_token
    assert sess.session_id


async def test_refresh_returns_new_access_and_rotates_refresh(test_db, seed_workspace):
    wid, uid = seed_workspace
    sess = await create_session(
        test_db, KEY, user_id=uid, workspace_id=wid,
        access_ttl_min=30, refresh_ttl_days=30,
    )
    new = await refresh_session(
        test_db, KEY, refresh_token=sess.refresh_token,
        access_ttl_min=30, refresh_ttl_days=30,
    )
    assert new.access_token != sess.access_token
    assert new.refresh_token != sess.refresh_token
    with pytest.raises(RefreshTokenInvalid):
        await refresh_session(
            test_db, KEY, refresh_token=sess.refresh_token,
            access_ttl_min=30, refresh_ttl_days=30,
        )


async def test_revoke_blocks_refresh(test_db, seed_workspace):
    wid, uid = seed_workspace
    sess = await create_session(
        test_db, KEY, user_id=uid, workspace_id=wid,
        access_ttl_min=30, refresh_ttl_days=30,
    )
    await revoke_session(test_db, sess.session_id)
    with pytest.raises(SessionRevoked):
        await refresh_session(
            test_db, KEY, refresh_token=sess.refresh_token,
            access_ttl_min=30, refresh_ttl_days=30,
        )
