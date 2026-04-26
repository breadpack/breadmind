from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status, Query
from pydantic import BaseModel, EmailStr

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.errors import Forbidden
from breadmind.messenger.service.user_service import (
    list_users, get_user, update_user_profile, deactivate_user,
)
from breadmind.messenger.auth.invite import create_invite


router = APIRouter(tags=["users"])


class UserResp(BaseModel):
    id: UUID
    workspace_id: UUID
    external_id: Optional[str]
    email: str
    kind: str
    display_name: str
    real_name: Optional[str]
    avatar_url: Optional[str]
    status_text: Optional[str]
    status_emoji: Optional[str]
    timezone: Optional[str]
    locale: str
    role: str
    joined_at: datetime
    deactivated_at: Optional[datetime]


class UsersListResp(BaseModel):
    users: list[UserResp]


class InviteReq(BaseModel):
    email: EmailStr
    role: str = "member"
    channel_ids: Optional[list[UUID]] = None


class ProfileUpdateReq(BaseModel):
    display_name: Optional[str] = None
    real_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status_text: Optional[str] = None
    status_emoji: Optional[str] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None


@router.get("/workspaces/{wid}/users", response_model=UsersListResp)
async def list_users_endpoint(
    kind: Optional[str] = None,
    active: bool = True,
    email: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    rows = await list_users(
        db, workspace_id=ctx.workspace_id,
        kind=kind, active=active, email=email, limit=limit,
    )
    return UsersListResp(users=[UserResp(**asdict(r)) for r in rows])


@router.post("/workspaces/{wid}/users", response_model=UserResp,
             status_code=status.HTTP_201_CREATED)
async def invite_user_endpoint(
    body: InviteReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if ctx.user.role in ("guest", "single_channel_guest"):
        raise Forbidden("guests cannot invite")
    await create_invite(
        db, workspace_id=ctx.workspace_id, email=body.email,
        invited_by=ctx.user.id, role=body.role, ttl_days=14,
        channel_ids=body.channel_ids,
    )
    # placeholder response — real user only exists after invite is accepted.
    return UserResp(
        id=uuid4(), workspace_id=ctx.workspace_id, external_id=None,
        email=body.email, kind="human", display_name=body.email,
        real_name=None, avatar_url=None, status_text="pending invite",
        status_emoji=None, timezone=None, locale="ko", role=body.role,
        joined_at=datetime.now(), deactivated_at=None,
    )


@router.get("/workspaces/{wid}/users/{uid}", response_model=UserResp)
async def get_user_endpoint(
    uid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    row = await get_user(db, workspace_id=ctx.workspace_id, user_id=uid)
    return UserResp(**asdict(row))


@router.patch("/workspaces/{wid}/users/{uid}/profile", response_model=UserResp)
async def patch_profile_endpoint(
    uid: UUID,
    body: ProfileUpdateReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if uid != ctx.user.id and ctx.user.role not in ("owner", "admin"):
        raise Forbidden("can only edit own profile")
    row = await update_user_profile(
        db, workspace_id=ctx.workspace_id, user_id=uid,
        **body.model_dump(exclude_unset=True),
    )
    return UserResp(**asdict(row))


@router.delete("/workspaces/{wid}/users/{uid}", status_code=204)
async def deactivate_user_endpoint(
    uid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if ctx.user.role not in ("owner", "admin"):
        raise Forbidden("admin only")
    await deactivate_user(db, workspace_id=ctx.workspace_id, user_id=uid)
