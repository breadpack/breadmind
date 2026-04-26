# src/breadmind/messenger/api/v1/search.py
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from breadmind.messenger.api.v1.deps import (
    get_db, get_workspace_context, WorkspaceContext,
)
from breadmind.messenger.service.search_service import (
    fts_search_messages, semantic_search_messages, reciprocal_rank_fusion, SearchHit,
)


router = APIRouter(tags=["search"])


class SearchHitResp(BaseModel):
    kind: str
    score: float
    message: Optional[dict] = None


class SearchResp(BaseModel):
    results: list[SearchHitResp]


@router.get("/workspaces/{wid}/search", response_model=SearchResp)
async def search_endpoint(
    request: Request,
    q: str,
    kind: str = "message",
    hybrid: bool = False,
    limit: int = Query(20, ge=1, le=100),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    db = Depends(get_db),
):
    fts = await fts_search_messages(
        db, workspace_id=ctx.workspace_id, user_id=ctx.user.id,
        user_role=ctx.user.role, query=q, limit=limit * 2,
    )
    semantic: list[SearchHit] = []
    if hybrid:
        embedder = getattr(request.app.state, "embedder", None)
        if embedder is not None:
            try:
                qvec = (await embedder.embed_batch([q]))[0]
                semantic = await semantic_search_messages(
                    db, workspace_id=ctx.workspace_id, user_id=ctx.user.id,
                    user_role=ctx.user.role, query_embedding=qvec, limit=limit * 2,
                )
            except Exception:
                semantic = []
    if hybrid and semantic:
        merged = reciprocal_rank_fusion(fts, semantic, top_n=limit)
    else:
        merged = fts[:limit]
    return SearchResp(results=[
        SearchHitResp(
            kind=h.kind, score=h.score,
            message={
                "id": str(h.message_id), "channel_id": str(h.channel_id),
                "text": h.text,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            },
        ) for h in merged
    ])
