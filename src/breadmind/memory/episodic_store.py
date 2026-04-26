from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Protocol

from breadmind.core.otel import with_span
from breadmind.memory.event_types import SignalKind, keyword_extract
from breadmind.storage.database import Database
from breadmind.storage.models import EpisodicNote

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EpisodicFilter:
    kinds: list[SignalKind] | None = None
    tool_name: str | None = None
    tool_args_digest: str | None = None
    keywords: list[str] | None = None
    pinned_only: bool = False
    org_id: uuid.UUID | None = None


class EpisodicStore(Protocol):
    async def write(self, note: EpisodicNote) -> int: ...
    async def search(
        self,
        user_id: str | None,
        query: str | None,
        filters: EpisodicFilter,
        limit: int,
    ) -> list[EpisodicNote]: ...


class PostgresEpisodicStore:
    """SQL-backed store. Phase 2 swaps in a pgvector-aware variant of `search`."""

    def __init__(self, db: Database):
        self.db = db

    async def write(self, note: EpisodicNote) -> int:
        return await self.db.save_note(note)

    async def search(
        self,
        user_id: str | None,
        query: str | None,
        filters: EpisodicFilter,
        limit: int,
    ) -> list[EpisodicNote]:
        kw = list(filters.keywords or [])
        if query:
            kw.extend(keyword_extract(query))
        kw = list(dict.fromkeys(kw))  # dedupe preserving order

        clauses: list[str] = []
        params: list = []

        def _p(v) -> str:
            params.append(v)
            return f"${len(params)}"

        if user_id is not None:
            clauses.append(f"(user_id IS NULL OR user_id = {_p(user_id)})")
        if filters.org_id is not None:
            _strict = os.environ.get("BREADMIND_EPISODIC_STRICT_ORG", "").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if _strict:
                clauses.append(f"org_id = {_p(filters.org_id)}")
            else:
                clauses.append(f"(org_id IS NULL OR org_id = {_p(filters.org_id)})")
        if filters.kinds:
            clauses.append(f"kind = ANY({_p([k.value for k in filters.kinds])}::text[])")
        if filters.tool_name:
            clauses.append(f"tool_name = {_p(filters.tool_name)}")
        if filters.pinned_only:
            clauses.append("pinned = TRUE")

        # Keyword/digest match — at least ONE of the optional matchers must hold (if any provided)
        opt: list[str] = []
        digest_param_idx: int | None = None
        if filters.tool_args_digest:
            digest_param_idx = len(params) + 1  # captured BEFORE _p() to use in ORDER BY
            opt.append(f"tool_args_digest = {_p(filters.tool_args_digest)}")
        if kw:
            opt.append(f"keywords && {_p(kw)}::text[]")
        if opt:
            clauses.append("(" + " OR ".join(opt) + ")")

        where = " AND ".join(clauses) if clauses else "TRUE"

        # Ordering:
        # 1. exact digest match first (if requested)
        # 2. pinned first
        # 3. failure outcome boosted (risk-aware)
        # 4. recency
        digest_clause = (
            f"(CASE WHEN tool_args_digest IS NOT NULL AND tool_args_digest = ${digest_param_idx} "
            f"THEN 0 ELSE 1 END) ASC,"
        ) if digest_param_idx is not None else ""

        order_clause = f"""
            {digest_clause}
            (CASE WHEN pinned THEN 0 ELSE 1 END) ASC,
            (CASE WHEN outcome = 'failure' THEN 0
                  WHEN outcome = 'success' THEN 1
                  ELSE 2 END) ASC,
            created_at DESC
        """

        sql = f"""
            SELECT * FROM episodic_notes
            WHERE {where}
            ORDER BY {order_clause}
            LIMIT {_p(limit)}
        """
        with with_span(
            "memory.episodic.search",
            attributes={"limit": str(limit)},
        ):
            async with self.db.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            return [self.db._row_to_note(r) for r in rows]
