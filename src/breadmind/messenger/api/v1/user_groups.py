from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.errors import Forbidden
from breadmind.messenger.service.user_group_service import (
    list_groups,
    get_group,
    create_group,
    update_group,
    delete_group,
    list_group_members,
    set_group_members,
)


router = APIRouter(tags=["user_groups"])


class GroupCreateReq(BaseModel):
    handle: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class GroupUpdateReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    handle: Optional[str] = None


class GroupMembersReq(BaseModel):
    user_ids: list[UUID]


class GroupResp(BaseModel):
    id: UUID
    workspace_id: UUID
    handle: str
    name: str
    description: Optional[str]
    created_by: Optional[UUID]
    created_at: datetime


class GroupsListResp(BaseModel):
    groups: list[GroupResp]


class GroupMembersResp(BaseModel):
    user_ids: list[UUID]


def _is_admin(ctx: WorkspaceContext) -> bool:
    return ctx.user.role in ("owner", "admin")


@router.get("/workspaces/{wid}/user-groups", response_model=GroupsListResp)
async def get_user_groups(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    rows = await list_groups(db, workspace_id=ctx.workspace_id)
    return GroupsListResp(groups=[GroupResp(**asdict(r)) for r in rows])


@router.post(
    "/workspaces/{wid}/user-groups",
    response_model=GroupResp,
    status_code=status.HTTP_201_CREATED,
)
async def post_user_group(
    body: GroupCreateReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not _is_admin(ctx):
        raise Forbidden("admin role required to create user groups")
    row = await create_group(
        db,
        workspace_id=ctx.workspace_id,
        handle=body.handle,
        name=body.name,
        description=body.description,
        created_by=ctx.user.id,
    )
    return GroupResp(**asdict(row))


@router.patch("/workspaces/{wid}/user-groups/{gid}", response_model=GroupResp)
async def patch_user_group(
    gid: UUID,
    body: GroupUpdateReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not _is_admin(ctx):
        raise Forbidden("admin role required to update user groups")
    row = await update_group(
        db,
        workspace_id=ctx.workspace_id,
        group_id=gid,
        **body.model_dump(exclude_unset=True),
    )
    return GroupResp(**asdict(row))


@router.delete(
    "/workspaces/{wid}/user-groups/{gid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_group(
    gid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not _is_admin(ctx):
        raise Forbidden("admin role required to delete user groups")
    await delete_group(db, workspace_id=ctx.workspace_id, group_id=gid)


@router.get(
    "/workspaces/{wid}/user-groups/{gid}/members",
    response_model=GroupMembersResp,
)
async def get_group_members(
    gid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    # verify group belongs to workspace
    await get_group(db, workspace_id=ctx.workspace_id, group_id=gid)
    user_ids = await list_group_members(db, group_id=gid)
    return GroupMembersResp(user_ids=user_ids)


@router.put(
    "/workspaces/{wid}/user-groups/{gid}/members",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def put_group_members(
    gid: UUID,
    body: GroupMembersReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if not _is_admin(ctx):
        raise Forbidden("admin role required to set group members")
    # verify group belongs to workspace
    await get_group(db, workspace_id=ctx.workspace_id, group_id=gid)
    await set_group_members(db, group_id=gid, user_ids=body.user_ids)
