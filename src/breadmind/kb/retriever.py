from __future__ import annotations

import logging
from uuid import UUID

from breadmind.kb.types import KBHit, Source

logger = logging.getLogger(__name__)

_VECTOR_LIMIT = 20
_FTS_LIMIT = 20
_RRF_K = 60


class KBRetriever:
    """Hybrid retrieval for org_knowledge: pgvector HNSW + Postgres tsvector BM25.

    Pipeline per `search()`:
      1. Fetch user's project membership (via ACL) — caller passes project_id.
      2. Vector top-20 (cosine) + FTS top-20 (websearch_to_tsquery).
      3. RRF fuse to a single ranked list.
      4. SQL-level ACL filter (channel visibility) — defensive second pass via ACL.
      5. Load kb_sources for remaining top_k rows.
    """

    def __init__(self, db, embedder, acl) -> None:
        self._db = db
        self._embedder = embedder
        self._acl = acl

    async def _vector_search(
        self, query: str, project_id: UUID, limit: int,
    ) -> list[tuple[int, float]]:
        embedding = await self._embedder.encode(query)
        if embedding is None:
            return []
        vec_literal = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, 1 - (embedding <=> $1::vector) AS similarity
                FROM org_knowledge
                WHERE project_id = $2
                  AND superseded_by IS NULL
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector ASC
                LIMIT $3
                """,
                vec_literal, project_id, limit,
            )
        return [(r["id"], float(r["similarity"])) for r in rows]

    async def _fts_search(
        self, query: str, project_id: UUID, limit: int,
    ) -> list[tuple[int, float]]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, ts_rank(tsv, websearch_to_tsquery('simple', $1)) AS rank
                FROM org_knowledge
                WHERE project_id = $2
                  AND superseded_by IS NULL
                  AND tsv @@ websearch_to_tsquery('simple', $1)
                ORDER BY rank DESC
                LIMIT $3
                """,
                query, project_id, limit,
            )
        return [(r["id"], float(r["rank"])) for r in rows]

    @staticmethod
    def _rrf_fuse(
        vector_hits: list[tuple[int, float]],
        fts_hits: list[tuple[int, float]],
        k: int = _RRF_K,
    ) -> list[tuple[int, float]]:
        """Reciprocal Rank Fusion. Higher is better."""
        scores: dict[int, float] = {}
        for rank, (kid, _sim) in enumerate(vector_hits, start=1):
            scores[kid] = scores.get(kid, 0.0) + 1.0 / (k + rank)
        for rank, (kid, _sim) in enumerate(fts_hits, start=1):
            scores[kid] = scores.get(kid, 0.0) + 1.0 / (k + rank)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # ------------------------------------------------------------------
    # Public search entry-point
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        user_id: str,
        project_id: UUID,
        top_k: int = 5,
    ) -> list[KBHit]:
        """Full hybrid-search pipeline: vector + FTS → RRF → ACL filter → load."""
        vec_hits = await self._vector_search(query, project_id, _VECTOR_LIMIT)
        fts_hits = await self._fts_search(query, project_id, _FTS_LIMIT)
        fused = self._rrf_fuse(vec_hits, fts_hits)
        if not fused:
            return []
        candidate_ids = [kid for kid, _ in fused]
        # SQL-level ACL filter: drop rows whose source_channel is private and
        # the user is not a member of that channel.
        allowed_ids = await self._sql_acl_filter(user_id, project_id, candidate_ids)
        # Defensive second pass — let the ACLResolver enforce anything missed.
        allowed_ids = set(
            await self._acl.filter_knowledge(user_id, project_id, list(allowed_ids))
        )
        ranked = [(kid, s) for kid, s in fused if kid in allowed_ids][:top_k]
        if not ranked:
            return []
        return await self._load_hits(ranked)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _sql_acl_filter(
        self,
        user_id: str,
        project_id: UUID,
        candidate_ids: list[int],
    ) -> set[int]:
        """Drop rows whose source_channel is set and the user cannot read it.

        Uses one acquire() block (one pool checkout) consistent with Tasks 2/3/4.
        """
        if not candidate_ids:
            return set()
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, source_channel
                FROM org_knowledge
                WHERE id = ANY($1::bigint[])
                  AND project_id = $2
                """,
                candidate_ids, project_id,
            )
        allowed: set[int] = set()
        for row in rows:
            ch = row["source_channel"]
            if ch is None:
                allowed.add(row["id"])
                continue
            if await self._acl.can_read_channel(user_id, ch):
                allowed.add(row["id"])
        return allowed

    async def _load_hits(
        self,
        ranked: list[tuple[int, float]],
    ) -> list[KBHit]:
        """Load titles, bodies, and sources for ranked candidates.

        Uses a single acquire() block covering both queries (one pool checkout).
        """
        ids = [kid for kid, _ in ranked]
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, title, body FROM org_knowledge WHERE id = ANY($1::bigint[])",
                ids,
            )
            src_rows = await conn.fetch(
                "SELECT knowledge_id, source_type, source_uri, source_ref "
                "FROM kb_sources WHERE knowledge_id = ANY($1::bigint[])",
                ids,
            )
        by_id = {r["id"]: r for r in rows}
        sources_by_id: dict[int, list[Source]] = {}
        for s in src_rows:
            sources_by_id.setdefault(s["knowledge_id"], []).append(
                Source(
                    type=s["source_type"],
                    uri=s["source_uri"],
                    ref=s["source_ref"],
                )
            )
        hits: list[KBHit] = []
        for kid, score in ranked:
            row = by_id.get(kid)
            if row is None:
                continue
            hits.append(
                KBHit(
                    knowledge_id=kid,
                    title=row["title"],
                    body=row["body"],
                    score=score,
                    sources=sources_by_id.get(kid, []),
                )
            )
        return hits
