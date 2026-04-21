"""ReviewQueue: lifecycle for promotion_candidates."""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from breadmind.kb.types import ExtractedCandidate, PromotionCandidate

logger = logging.getLogger(__name__)

# Cosine-similarity threshold for superseded_by chaining (spec §6.2)
_SIMILARITY_THRESHOLD = 0.88
# Slack backpressure threshold (spec §8.1) — enforced later (Task 11)
_BACKPRESSURE_LIMIT = 500


class ReviewQueue:
    def __init__(self, db, slack_client) -> None:
        self._db = db
        self._slack = slack_client

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
