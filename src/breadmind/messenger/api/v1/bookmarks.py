from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.service.bookmark_service import (
    add_bookmark, list_bookmarks, remove_bookmark,
)


router = APIRouter(tags=["bookmarks"])


class BookmarkReq(BaseModel):
    message_id: UUID
    reminder_at: Optional[datetime] = None


class BookmarkResp(BaseModel):
    user_id: UUID
    message_id: UUID
    saved_at: datetime
    reminder_at: Optional[datetime]


class BookmarksListResp(BaseModel):
    bookmarks: list[BookmarkResp]


@router.post("/workspaces/{wid}/bookmarks", status_code=status.HTTP_201_CREATED)
async def add_bookmark_endpoint(
    body: BookmarkReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    await add_bookmark(db, user_id=ctx.user.id, message_id=body.message_id, reminder_at=body.reminder_at)


@router.get("/workspaces/{wid}/bookmarks", response_model=BookmarksListResp)
async def list_bookmarks_endpoint(
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    rows = await list_bookmarks(db, user_id=ctx.user.id, workspace_id=ctx.workspace_id)
    return BookmarksListResp(bookmarks=[BookmarkResp(**asdict(r)) for r in rows])


@router.delete("/workspaces/{wid}/bookmarks/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_bookmark_endpoint(
    message_id: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db=Depends(get_db),
):
    await remove_bookmark(db, user_id=ctx.user.id, message_id=message_id)
