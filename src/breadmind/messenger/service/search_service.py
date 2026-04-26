# src/breadmind/messenger/service/search_service.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SearchHit:
    kind: str            # "message" | "file" | "kb"
    score: float
    message_id: Optional[UUID] = None
    channel_id: Optional[UUID] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None
    highlight: Optional[str] = None


async def _visible_channel_ids(
    db, *, workspace_id: UUID, user_id: UUID, user_role: str,
) -> list[UUID]:
    if user_role in ("owner", "admin"):
        rows = await db.fetch(
            "SELECT id FROM channels WHERE workspace_id = $1", workspace_id,
        )
    else:
        if user_role == "member":
            rows = await db.fetch(
                """SELECT id FROM channels
                   WHERE workspace_id = $1 AND (kind = 'public' OR id IN
                     (SELECT channel_id FROM channel_members WHERE user_id = $2))""",
                workspace_id, user_id,
            )
        else:
            rows = await db.fetch(
                """SELECT id FROM channels
                   WHERE workspace_id = $1 AND id IN
                     (SELECT channel_id FROM channel_members WHERE user_id = $2)""",
                workspace_id, user_id,
            )
    return [r["id"] for r in rows]


async def fts_search_messages(
    db, *, workspace_id: UUID, user_id: UUID, user_role: str,
    query: str, limit: int = 50,
) -> list[SearchHit]:
    visible = await _visible_channel_ids(
        db, workspace_id=workspace_id, user_id=user_id, user_role=user_role,
    )
    if not visible:
        return []
    rows = await db.fetch(
        """SELECT id, channel_id, text, created_at,
                  ts_rank(text_tsvector, websearch_to_tsquery('simple', $1)) AS score
           FROM messages
           WHERE channel_id = ANY($2::uuid[])
             AND deleted_at IS NULL
             AND text_tsvector @@ websearch_to_tsquery('simple', $1)
           ORDER BY score DESC
           LIMIT $3""",
        query, visible, limit,
    )
    return [
        SearchHit(
            kind="message", score=float(r["score"]),
            message_id=r["id"], channel_id=r["channel_id"],
            text=r["text"], created_at=r["created_at"],
        )
        for r in rows
    ]


async def semantic_search_messages(
    db, *, workspace_id: UUID, user_id: UUID, user_role: str,
    query_embedding: list[float], limit: int = 50,
) -> list[SearchHit]:
    visible = await _visible_channel_ids(
        db, workspace_id=workspace_id, user_id=user_id, user_role=user_role,
    )
    if not visible:
        return []
    # asyncpg expects vector as a string '[a,b,c,...]' or relies on the driver registration.
    # Convert to PG vector literal explicitly:
    vec_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
    rows = await db.fetch(
        """SELECT id, channel_id, text, created_at,
                  1.0 - (embedding <=> $1::vector) AS score
           FROM messages
           WHERE channel_id = ANY($2::uuid[])
             AND deleted_at IS NULL
             AND embedding IS NOT NULL
           ORDER BY embedding <=> $1::vector
           LIMIT $3""",
        vec_str, visible, limit,
    )
    return [
        SearchHit(
            kind="message", score=float(r["score"]),
            message_id=r["id"], channel_id=r["channel_id"],
            text=r["text"], created_at=r["created_at"],
        )
        for r in rows
    ]


def reciprocal_rank_fusion(
    *result_lists: list[SearchHit], k: int = 60, top_n: int = 20,
) -> list[SearchHit]:
    scores: dict[UUID, float] = {}
    representatives: dict[UUID, SearchHit] = {}
    for results in result_lists:
        for rank, hit in enumerate(results):
            if hit.message_id is None:
                continue
            scores[hit.message_id] = scores.get(hit.message_id, 0.0) + 1.0 / (k + rank + 1)
            representatives.setdefault(hit.message_id, hit)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    out = []
    for mid, s in ranked:
        h = representatives[mid]
        out.append(SearchHit(
            kind="message", score=s, message_id=mid,
            channel_id=h.channel_id, text=h.text, created_at=h.created_at,
        ))
    return out
