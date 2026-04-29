"""Publisher emits the right channel names."""
from __future__ import annotations
from uuid import UUID
from unittest.mock import AsyncMock

import pytest

from breadmind.messenger.acl.realtime import (
    publish_user_channel_change,
    publish_user_invalidate,
)


async def test_publish_user_channel_add():
    r = AsyncMock()
    uid = UUID("00000000-0000-0000-0000-000000000001")
    cid = UUID("00000000-0000-0000-0000-000000000002")
    await publish_user_channel_change(r, user_id=uid, channel_id=cid, op="add")
    r.publish.assert_awaited_once_with(
        f"acl:invalidate:user:{uid}:channel:{cid}:add", ""
    )


async def test_publish_user_channel_remove():
    r = AsyncMock()
    uid = UUID("00000000-0000-0000-0000-000000000001")
    cid = UUID("00000000-0000-0000-0000-000000000002")
    await publish_user_channel_change(r, user_id=uid, channel_id=cid, op="remove")
    r.publish.assert_awaited_once_with(
        f"acl:invalidate:user:{uid}:channel:{cid}:remove", ""
    )


async def test_publish_user_channel_invalid_op():
    r = AsyncMock()
    with pytest.raises(ValueError):
        await publish_user_channel_change(
            r, user_id=UUID(int=1), channel_id=UUID(int=2), op="modify",
        )


async def test_publish_user_invalidate():
    r = AsyncMock()
    uid = UUID("00000000-0000-0000-0000-000000000003")
    await publish_user_invalidate(r, user_id=uid)
    r.publish.assert_awaited_once_with(f"acl:invalidate:user:{uid}", "")


async def test_publish_failure_swallowed():
    r = AsyncMock()
    r.publish.side_effect = RuntimeError("redis down")
    # Must not raise.
    await publish_user_invalidate(r, user_id=UUID(int=1))


async def test_publish_failure_swallowed_user_channel():
    """Failure path covered for publish_user_channel_change too."""
    r = AsyncMock()
    r.publish.side_effect = RuntimeError("redis down")
    # Must not raise.
    await publish_user_channel_change(
        r, user_id=UUID(int=1), channel_id=UUID(int=2), op="add",
    )
