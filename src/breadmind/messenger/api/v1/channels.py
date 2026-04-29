from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status, Query
from pydantic import BaseModel, Field

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.errors import Forbidden
from breadmind.messenger.acl.channel import can_user_admin_channel
from breadmind.messenger.acl.cache import VisibleChannelsCache
from breadmind.messenger.service.channel_service import (
    create_channel, get_channel, list_channels, update_channel, archive_channel,
)


router = APIRouter(tags=["channels"])


class ChannelCreateReq(BaseModel):
    kind: str = Field(pattern="^(public|private)$")
    name: str = Field(min_length=1, max_length=80)
    topic: Optional[str] = None
    purpose: Optional[str] = None
    initial_member_ids: Optional[list[UUID]] = None


class ChannelUpdateReq(BaseModel):
    name: Optional[str] = None
    topic: Optional[str] = None
    purpose: Optional[str] = None
    posting_policy: Optional[str] = Field(default=None, pattern="^(all|admins|specific_roles)$")


class ChannelResp(BaseModel):
    id: UUID
    workspace_id: UUID
    kind: str
    name: Optional[str]
    topic: Optional[str]
    purpose: Optional[str]
    is_general: bool
    is_archived: bool
    posting_policy: str
    last_message_at: Optional[datetime]
    created_at: datetime


class ChannelsListResp(BaseModel):
    channels: list[ChannelResp]


@router.post("/workspaces/{wid}/channels", response_model=ChannelResp, status_code=status.HTTP_201_CREATED)
async def post_channel(
    body: ChannelCreateReq,
    request: Request,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if ctx.user.role in ("guest", "single_channel_guest"):
        raise Forbidden("guests cannot create channels")
    row = await create_channel(
        db, workspace_id=ctx.workspace_id, kind=body.kind, name=body.name,
        topic=body.topic, purpose=body.purpose,
        created_by=ctx.user.id, initial_member_ids=body.initial_member_ids,
    )
    cache = VisibleChannelsCache(request.app.state.redis, ttl_sec=300)
    await cache.invalidate_workspace(ctx.workspace_id)
    return ChannelResp(**asdict(row))


@router.get("/workspaces/{wid}/channels", response_model=ChannelsListResp)
async def get_channels(
    kind: Optional[str] = None,
    archived: bool = False,
    limit: int = Query(50, ge=1, le=200),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    rows = await list_channels(db, workspace_id=ctx.workspace_id, kind=kind, archived=archived, limit=limit)
    return ChannelsListResp(channels=[ChannelResp(**asdict(r)) for r in rows])


@router.get("/workspaces/{wid}/channels/{cid}", response_model=ChannelResp)
async def get_one_channel(
    cid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    row = await get_channel(db, workspace_id=ctx.workspace_id, channel_id=cid)
    return ChannelResp(**asdict(row))


@router.patch("/workspaces/{wid}/channels/{cid}", response_model=ChannelResp)
async def patch_channel(
    cid: UUID,
    body: ChannelUpdateReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_admin_channel(db, user_id=ctx.user.id, channel_id=cid):
        raise Forbidden("channel admin role required")
    row = await update_channel(db, workspace_id=ctx.workspace_id, channel_id=cid, **body.model_dump(exclude_unset=True))
    return ChannelResp(**asdict(row))


@router.post("/workspaces/{wid}/channels/{cid}/archive", status_code=204)
async def archive_endpoint(
    cid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not await can_user_admin_channel(db, user_id=ctx.user.id, channel_id=cid):
        raise Forbidden("channel admin role required")
    await archive_channel(db, workspace_id=ctx.workspace_id, channel_id=cid)
    # Spec D8 archive policy: archive != revoke. Members keep read-only
    # visibility, so archive does NOT publish acl:invalidate :remove. Site 5
    # (delete_channel `:remove` per member) is deferred until a hard-delete
    # endpoint is added — see realtime.py for FU note.
