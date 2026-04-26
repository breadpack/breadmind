from __future__ import annotations
import dataclasses
from datetime import datetime
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from breadmind.messenger.api.v1.deps import (
    get_db, get_current_user, get_workspace_context, CurrentUser, WorkspaceContext,
)
from breadmind.messenger.errors import Forbidden
from breadmind.messenger.service.workspace_service import (
    create_workspace, get_workspace, list_workspaces_for_user, update_workspace,
)


router = APIRouter(tags=["workspaces"])


class WorkspaceCreateReq(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=64)
    domain: Optional[str] = None


class WorkspaceUpdateReq(BaseModel):
    name: Optional[str] = None
    icon_url: Optional[str] = None
    domain: Optional[str] = None


class WorkspaceResp(BaseModel):
    id: UUID
    name: str
    slug: str
    domain: Optional[str]
    icon_url: Optional[str]
    plan: str
    archived_at: Optional[datetime]
    default_channel_id: Optional[UUID]


@router.post("/workspaces", response_model=WorkspaceResp, status_code=status.HTTP_201_CREATED)
async def post_workspace(
    body: WorkspaceCreateReq,
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    row = await create_workspace(
        db, name=body.name, slug=body.slug,
        created_by=user.id, domain=body.domain,
    )
    return WorkspaceResp(**dataclasses.asdict(row))


@router.get("/workspaces", response_model=list[WorkspaceResp])
async def get_workspaces(
    user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    rows = await list_workspaces_for_user(db, user_email=user.email)
    return [WorkspaceResp(**dataclasses.asdict(r)) for r in rows]


@router.get("/workspaces/{wid}", response_model=WorkspaceResp)
async def get_one_workspace(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    row = await get_workspace(db, ctx.workspace_id)
    return WorkspaceResp(**dataclasses.asdict(row))


@router.patch("/workspaces/{wid}", response_model=WorkspaceResp)
async def patch_workspace_endpoint(
    body: WorkspaceUpdateReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    if ctx.user.role not in ("owner", "admin"):
        raise Forbidden("admin role required")
    row = await update_workspace(
        db, ctx.workspace_id,
        name=body.name, icon_url=body.icon_url, domain=body.domain,
    )
    return WorkspaceResp(**dataclasses.asdict(row))
