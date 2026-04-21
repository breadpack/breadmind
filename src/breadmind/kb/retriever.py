from __future__ import annotations

import logging
from uuid import UUID

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
