# src/breadmind/messenger/api/v1/messages.py
from __future__ import annotations
import json
from dataclasses import asdict
from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status, Query, Header, Request
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.errors import Forbidden, NotFound, Conflict
from breadmind.messenger.acl.channel import can_user_post_message
from breadmind.messenger.acl.message import can_user_edit_message, can_user_see_message
from breadmind.messenger.idempotency import (
    IdempotencyStore, hash_request, IdempotencyConflict, ClientMsgIdDedup,
)
from breadmind.messenger.service.message_service import (
    post_message, get_message, get_message_by_client_msg_id,
    edit_message, delete_message, list_messages, MessageRow,
)


router = APIRouter(tags=["messages"])


class MessagePostReq(BaseModel):
    text: Optional[str] = None
    blocks: Optional[list[dict]] = None
    parent_id: Optional[UUID] = None
    client_msg_id: Optional[UUID] = None


class MessageEditReq(BaseModel):
    text: Optional[str] = None
    blocks: Optional[list[dict]] = None


class MessageResp(BaseModel):
    id: UUID
    workspace_id: UUID
    channel_id: UUID
    author_id: UUID
    parent_id: Optional[UUID]
    kind: str
    text: Optional[str]
    blocks: list
    created_at: datetime
    edited_at: Optional[datetime]
    deleted_at: Optional[datetime]


class MessageListResp(BaseModel):
    messages: list[MessageResp]
    pagination: dict


def _to_resp(row: MessageRow) -> MessageResp:
    d = asdict(row)
    d.pop("ts_seq", None)
    return MessageResp(**d)


@router.post("/workspaces/{wid}/channels/{cid}/messages",
             response_model=MessageResp,
             status_code=status.HTTP_201_CREATED)
async def post_message_endpoint(
    cid: UUID,
    body: MessagePostReq,
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db = Depends(get_db),
):
    if not await can_user_post_message(db, user_id=ctx.user.id, channel_id=cid):
        raise Forbidden("cannot post in this channel")

    store = None
    rhash = None
    if idempotency_key:
        store = IdempotencyStore(request.app.state.redis)
        body_bytes = json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
        rhash = hash_request("POST", str(request.url.path), body_bytes)
        try:
            cached = await store.get_or_lock(idempotency_key, request_hash=rhash)
        except IdempotencyConflict as e:
            raise Conflict(str(e)) from e
        if cached is not None and cached is not store.IN_PROGRESS_SENTINEL:
            return MessageResp.model_validate_json(cached.body)

    # Body-keyed dedup: scope = (sender_id, channel_id, client_msg_id), 24h TTL.
    # Distinct from header-based Idempotency-Key; protects against client retries
    # at the application layer (spec D9). Redis is the fast-path retry guard;
    # the DB UNIQUE index ``messages_client_msg_id`` on (workspace_id,
    # client_msg_id) is the strict correctness backstop for concurrent racers
    # that both miss Redis (handled below in ``except UniqueViolationError``).
    dedup: ClientMsgIdDedup | None = None
    if body.client_msg_id is not None:
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            dedup = ClientMsgIdDedup(redis)
            existing_id = await dedup.lookup(
                sender_id=ctx.user.id,
                channel_id=cid,
                client_msg_id=body.client_msg_id,
            )
            if existing_id is not None:
                try:
                    existing_row = await get_message(
                        db, channel_id=cid, message_id=existing_id,
                    )
                    return _to_resp(existing_row)
                except NotFound:
                    # Stale dedup pointer (row deleted/expired). Fall through to insert.
                    pass

    try:
        row = await post_message(
            db, workspace_id=ctx.workspace_id, channel_id=cid,
            author_id=ctx.user.id, text=body.text, blocks=body.blocks,
            parent_id=body.parent_id, client_msg_id=body.client_msg_id,
        )
    except asyncpg.UniqueViolationError:
        # Concurrent racer with the same client_msg_id won the DB UNIQUE.
        # Look up the winner and return it (idempotent semantics per spec D9).
        if body.client_msg_id is None:
            raise  # Different unique violation, not the dedup race.
        existing = await get_message_by_client_msg_id(
            db, workspace_id=ctx.workspace_id, client_msg_id=body.client_msg_id,
        )
        if existing is None:
            raise  # Should never happen, but don't silently swallow.
        if dedup is not None:
            # Populate Redis with the winner's id so subsequent retries hit
            # the fast path instead of repeating the DB collision dance.
            await dedup.remember(
                sender_id=ctx.user.id, channel_id=cid,
                client_msg_id=body.client_msg_id, message_id=existing.id,
            )
        resp = _to_resp(existing)
        if store and idempotency_key:
            await store.put(
                idempotency_key, request_hash=rhash, status=201,
                body=resp.model_dump_json().encode(),
            )
        return resp
    if dedup is not None and body.client_msg_id is not None:
        await dedup.remember(
            sender_id=ctx.user.id, channel_id=cid,
            client_msg_id=body.client_msg_id, message_id=row.id,
        )
    resp = _to_resp(row)
    if store and idempotency_key:
        await store.put(
            idempotency_key, request_hash=rhash, status=201,
            body=resp.model_dump_json().encode(),
        )
    return resp


@router.get("/workspaces/{wid}/channels/{cid}/messages", response_model=MessageListResp)
async def list_messages_endpoint(
    cid: UUID,
    before: Optional[datetime] = None,
    after: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db = Depends(get_db),
):
    rows, has_more = await list_messages(
        db, channel_id=cid, before=before, after=after, limit=limit,
    )
    return MessageListResp(
        messages=[_to_resp(r) for r in rows],
        pagination={"has_more": has_more, "limit": limit},
    )


@router.get("/workspaces/{wid}/channels/{cid}/messages/{mid}", response_model=MessageResp)
async def get_message_endpoint(
    cid: UUID, mid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db = Depends(get_db),
):
    if not await can_user_see_message(db, user_id=ctx.user.id, message_id=mid):
        raise NotFound("message", str(mid))
    row = await get_message(db, channel_id=cid, message_id=mid)
    return _to_resp(row)


@router.patch("/workspaces/{wid}/channels/{cid}/messages/{mid}", response_model=MessageResp)
async def patch_message(
    cid: UUID, mid: UUID,
    body: MessageEditReq,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db = Depends(get_db),
):
    if not await can_user_edit_message(db, user_id=ctx.user.id, message_id=mid):
        raise Forbidden("cannot edit this message")
    row = await edit_message(
        db, channel_id=cid, message_id=mid,
        text=body.text, blocks=body.blocks, edited_by=ctx.user.id,
    )
    return _to_resp(row)


@router.delete("/workspaces/{wid}/channels/{cid}/messages/{mid}", status_code=204)
async def delete_message_endpoint(
    cid: UUID, mid: UUID,
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db = Depends(get_db),
):
    if not await can_user_edit_message(db, user_id=ctx.user.id, message_id=mid):
        raise Forbidden("cannot delete this message")
    await delete_message(db, channel_id=cid, message_id=mid)
