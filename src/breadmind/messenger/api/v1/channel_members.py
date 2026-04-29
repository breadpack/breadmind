from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.errors import Forbidden
from breadmind.messenger.acl.channel import can_user_admin_channel
from breadmind.messenger.acl.cache import VisibleChannelsCache
from breadmind.messenger.acl.realtime import publish_user_channel_change
from breadmind.messenger.service.channel_service import add_members, remove_member


router = APIRouter(tags=["channel_members"])


class MembersReq(BaseModel):
    user_ids: list[UUID]


@router.post("/workspaces/{wid}/channels/{cid}/members", status_code=201)
async def add_members_endpoint(
    cid: UUID,
    body: MembersReq,
    request: Request,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_admin_channel(db, user_id=ctx.user.id, channel_id=cid):
        raise Forbidden("channel admin role required")
    await add_members(db, channel_id=cid, user_ids=body.user_ids)
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        cache = VisibleChannelsCache(redis, ttl_sec=300)
        for uid in body.user_ids:
            await cache.invalidate_user(uid)
            await publish_user_channel_change(
                redis, user_id=uid, channel_id=cid, op="add",
            )
    return {"added": [str(u) for u in body.user_ids]}


@router.delete("/workspaces/{wid}/channels/{cid}/members/{uid}", status_code=204)
async def remove_member_endpoint(
    cid: UUID, uid: UUID,
    request: Request,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if uid != ctx.user.id and not await can_user_admin_channel(db, user_id=ctx.user.id, channel_id=cid):
        raise Forbidden("admin or self required")
    await remove_member(db, channel_id=cid, user_id=uid)
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        cache = VisibleChannelsCache(redis, ttl_sec=300)
        await cache.invalidate_user(uid)
        await publish_user_channel_change(
            redis, user_id=uid, channel_id=cid, op="remove",
        )
