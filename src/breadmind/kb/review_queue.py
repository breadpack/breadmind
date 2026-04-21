"""ReviewQueue: lifecycle for promotion_candidates."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from breadmind.kb import metrics as kb_metrics
from breadmind.kb.types import ExtractedCandidate, PromotionCandidate

logger = logging.getLogger(__name__)

# Cosine-similarity threshold for superseded_by chaining (spec §6.2)
_SIMILARITY_THRESHOLD = 0.88
# Slack backpressure threshold (spec §8.1) — enforced later (Task 11)
_BACKPRESSURE_LIMIT = 500


async def _embed_text(text: str) -> list[float]:
    """Default embedding helper.

    Tests monkeypatch ``breadmind.kb.review_queue._embed_text`` to return a
    deterministic stub vector without a real embedding backend. Production
    wiring will replace this stub in a later task (P5 ops).
    """
    # TODO(P5 ops): wire to EmbeddingService.encode via the DI container.
    raise NotImplementedError(
        "_embed_text must be monkey-patched in tests or wired in production"
    )


def _vec(values: list[float]) -> str:
    """Encode a list[float] as a pgvector literal string.

    Mirrors the convention used by KBRetriever (`retriever.py`): pgvector
    accepts ``'[f1,f2,...]'`` with 6-decimal precision when cast via
    ``$1::vector`` in SQL.
    """
    return "[" + ",".join(f"{float(v):.6f}" for v in values) + "]"


class ReviewQueue:
    def __init__(self, db, slack_client=None) -> None:
        self._db = db
        self._slack = slack_client

    @property
    def db(self):
        """Public alias for the underlying DB handle.

        The metrics / ops-readiness helpers (:meth:`refresh_backlog_metric`,
        :meth:`build_for_tests`) reach into the DB directly rather than via
        :meth:`acquire`, so they stay usable with lightweight asyncpg-style
        stubs that only implement ``fetchrow``/``fetch``/``execute``.
        """
        return self._db

    @classmethod
    async def build_for_tests(cls, *, pending: int = 0) -> "ReviewQueue":
        """Return a ReviewQueue wired against a deterministic in-memory DB.

        The ``pending`` argument controls what a subsequent
        :meth:`refresh_backlog_metric` call sees — useful for exercising
        the gauge publication path without a live postgres fixture.
        """
        return cls(db=_InMemoryBacklogDB(pending=pending), slack_client=None)

    async def refresh_backlog_metric(self) -> int:
        """Count pending ``promotion_candidates`` and publish to the
        ``breadmind_promotion_backlog`` Prometheus gauge. Returns the
        count so callers can log or act on it.

        Works with either a raw asyncpg-style handle (``db.fetchrow``
        exists directly — in-memory stubs and asyncpg Pools) or a
        Database wrapper that exposes ``acquire()`` (the production
        :class:`breadmind.storage.database.Database`).
        """
        sql = (
            "SELECT COUNT(*) AS n FROM promotion_candidates "
            "WHERE status='pending'"
        )
        if hasattr(self.db, "fetchrow"):
            row = await self.db.fetchrow(sql)
        else:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(sql)
        n = int(row["n"]) if row else 0
        try:
            kb_metrics.set_promotion_backlog(n)
        except Exception:  # pragma: no cover — metrics must never break prod
            logger.exception("set_promotion_backlog failed")
        return n

    async def enqueue(self, candidate: ExtractedCandidate) -> int:
        status = "needs_edit" if candidate.sensitive_flag else "pending"
        sources_json = [
            {
                "source_type": s.type,
                "source_uri": s.uri,
                "source_ref": s.ref,
            }
            for s in candidate.sources
        ]
        async with self._db.acquire() as conn:
            cid = await conn.fetchval(
                """
                INSERT INTO promotion_candidates
                    (project_id, extracted_from, original_user,
                     proposed_title, proposed_body, proposed_category,
                     sources_json, confidence, status, sensitive_flag)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
                RETURNING id
                """,
                candidate.project_id,
                "knowledge_extractor",
                candidate.original_user,
                candidate.proposed_title,
                candidate.proposed_body,
                candidate.proposed_category,
                json.dumps(sources_json),
                candidate.confidence,
                status,
                candidate.sensitive_flag,
            )
            await _audit(
                conn,
                actor="system",
                action="enqueue_candidate",
                subject_type="promotion_candidate",
                subject_id=str(cid),
                project_id=candidate.project_id,
                metadata={
                    "category": candidate.proposed_category,
                    "confidence": candidate.confidence,
                    "sensitive_flag": candidate.sensitive_flag,
                },
            )
        return int(cid)

    async def list_pending(
        self,
        project_id: UUID,
        limit: int = 20,
    ) -> list[PromotionCandidate]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, project_id, extracted_from, original_user,
                       proposed_title, proposed_body, proposed_category,
                       sources_json, confidence, status, sensitive_flag,
                       reviewer, reviewed_at, created_at
                FROM promotion_candidates
                WHERE project_id = $1 AND status IN ('pending', 'needs_edit')
                ORDER BY created_at ASC
                LIMIT $2
                """,
                project_id,
                limit,
            )
        return [
            PromotionCandidate(
                id=r["id"],
                project_id=r["project_id"],
                extracted_from=r["extracted_from"],
                original_user=r["original_user"],
                proposed_title=r["proposed_title"],
                proposed_body=r["proposed_body"],
                proposed_category=r["proposed_category"],
                sources_json=(
                    json.loads(r["sources_json"])
                    if isinstance(r["sources_json"], str)
                    else (r["sources_json"] or [])
                ),
                confidence=float(r["confidence"]),
                status=r["status"],
                reviewer=r["reviewer"],
                reviewed_at=r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
                created_at=r["created_at"].isoformat() if r["created_at"] else None,
                sensitive_flag=r["sensitive_flag"],
            )
            for r in rows
        ]

    async def approve(self, candidate_id: int, reviewer: str) -> int:
        """Promote a candidate into ``org_knowledge`` and notify its author.

        Transactional steps:
          1. ``SELECT ... FOR UPDATE`` the candidate, validating status.
          2. Generate an embedding via the module-level ``_embed_text``.
          3. Insert into ``org_knowledge`` (with embedding + promoted_* fields).
          4. Copy ``sources_json`` rows into ``kb_sources``.
          5. Detect a near-duplicate (cosine > ``_SIMILARITY_THRESHOLD``) in
             the same project and chain ``superseded_by`` on the older row.
          6. Mark the candidate ``approved`` + set reviewer/reviewed_at.
          7. Audit with action ``promote``.

        Outside the transaction, best-effort DM to the original contributor.
        Returns the new ``org_knowledge.id``.
        """
        async with self._db.acquire() as conn:
            async with conn.transaction():
                cand = await conn.fetchrow(
                    "SELECT * FROM promotion_candidates WHERE id=$1 FOR UPDATE",
                    candidate_id,
                )
                if not cand:
                    raise ValueError(f"candidate {candidate_id} not found")
                if cand["status"] not in ("pending", "needs_edit"):
                    raise ValueError(
                        f"candidate {candidate_id} status={cand['status']}"
                    )

                embedding = await _embed_text(
                    f"{cand['proposed_title']}\n{cand['proposed_body']}"
                )
                vec_literal = _vec(embedding)

                kid = await conn.fetchval(
                    """
                    INSERT INTO org_knowledge
                        (project_id, title, body, category, promoted_from,
                         promoted_by, promoted_at, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, now(), $7::vector)
                    RETURNING id
                    """,
                    cand["project_id"],
                    cand["proposed_title"],
                    cand["proposed_body"],
                    cand["proposed_category"],
                    cand["extracted_from"],
                    reviewer,
                    vec_literal,
                )

                # Copy sources (Task 6 writes column-name variant keys).
                raw = cand["sources_json"] or []
                if isinstance(raw, str):
                    raw = json.loads(raw)
                for s in raw:
                    await conn.execute(
                        """
                        INSERT INTO kb_sources
                            (knowledge_id, source_type, source_uri, source_ref)
                        VALUES ($1, $2, $3, $4)
                        """,
                        kid,
                        s.get("source_type"),
                        s.get("source_uri"),
                        s.get("source_ref"),
                    )

                # Detect near-duplicate existing knowledge → superseded_by chain
                dup_id = await conn.fetchval(
                    """
                    SELECT id FROM org_knowledge
                    WHERE project_id = $1
                      AND id <> $2
                      AND superseded_by IS NULL
                      AND embedding IS NOT NULL
                      AND 1 - (embedding <=> $3::vector) > $4
                    ORDER BY embedding <=> $3::vector
                    LIMIT 1
                    """,
                    cand["project_id"],
                    kid,
                    vec_literal,
                    _SIMILARITY_THRESHOLD,
                )
                if dup_id:
                    await conn.execute(
                        "UPDATE org_knowledge SET superseded_by=$1 WHERE id=$2",
                        kid,
                        dup_id,
                    )

                await conn.execute(
                    """
                    UPDATE promotion_candidates
                    SET status='approved', reviewer=$2, reviewed_at=now()
                    WHERE id=$1
                    """,
                    candidate_id,
                    reviewer,
                )

                await _audit(
                    conn,
                    actor=reviewer,
                    action="promote",
                    subject_type="org_knowledge",
                    subject_id=str(kid),
                    project_id=cand["project_id"],
                    metadata={
                        "candidate_id": candidate_id,
                        "category": cand["proposed_category"],
                        "superseded": dup_id,
                    },
                )

        # DM original user (best effort, outside transaction).
        if cand["original_user"]:
            try:
                opened = await self._slack.conversations_open(
                    users=cand["original_user"]
                )
                dm_channel = opened["channel"]["id"]
                await self._slack.chat_postMessage(
                    channel=dm_channel,
                    text=(
                        ":tada: Your contribution was promoted to the team KB: "
                        f"*{cand['proposed_title']}* (by <@{reviewer}>)."
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("DM contributor failed: %s", exc)

        return int(kid)

    async def reject(
        self,
        candidate_id: int,
        reviewer: str,
        reason: str,
    ) -> None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT project_id FROM promotion_candidates WHERE id=$1",
                candidate_id,
            )
            if not row:
                raise ValueError(f"candidate {candidate_id} not found")
            await conn.execute(
                """
                UPDATE promotion_candidates
                SET status='rejected', reviewer=$2, reviewed_at=now()
                WHERE id=$1
                """,
                candidate_id,
                reviewer,
            )
            await _audit(
                conn,
                actor=reviewer,
                action="reject",
                subject_type="promotion_candidate",
                subject_id=str(candidate_id),
                project_id=row["project_id"],
                metadata={"reason": reason},
            )

    async def needs_edit(
        self,
        candidate_id: int,
        reviewer: str,
        new_body: str,
    ) -> None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT project_id FROM promotion_candidates WHERE id=$1",
                candidate_id,
            )
            if not row:
                raise ValueError(f"candidate {candidate_id} not found")
            await conn.execute(
                """
                UPDATE promotion_candidates
                SET status='needs_edit', reviewer=$2, reviewed_at=now(),
                    proposed_body=$3
                WHERE id=$1
                """,
                candidate_id,
                reviewer,
                new_body,
            )
            await _audit(
                conn,
                actor=reviewer,
                action="needs_edit",
                subject_type="promotion_candidate",
                subject_id=str(candidate_id),
                project_id=row["project_id"],
                metadata={"body_chars": len(new_body)},
            )


class _InMemoryBacklogDB:
    """Minimal async-DB stub exposing only ``fetchrow`` for the
    :meth:`ReviewQueue.refresh_backlog_metric` path. Used by
    :meth:`ReviewQueue.build_for_tests` so metric tests can run without
    a postgres fixture.
    """

    def __init__(self, *, pending: int) -> None:
        self._pending = pending

    async def fetchrow(self, sql: str, *_args: Any) -> dict[str, int] | None:
        if "FROM promotion_candidates" in sql:
            return {"n": self._pending}
        return None

    @asynccontextmanager
    async def acquire(self):  # pragma: no cover — not exercised in facade tests
        yield self


async def _audit(
    conn,
    *,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    project_id: UUID | None,
    metadata: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO kb_audit_log
            (actor, action, subject_type, subject_id, project_id, metadata)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        """,
        actor,
        action,
        subject_type,
        subject_id,
        project_id,
        json.dumps(metadata, default=str),
    )
