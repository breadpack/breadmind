"""Feedback loop handlers: upvote/downvote/bookmark on query answers."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_RE_REVIEW_FLAG_THRESHOLD = 3  # Spec §6.4 "임계 초과" — conservative default


def build_feedback_blocks(knowledge_id: int, query_id: str) -> list[dict]:
    """Return Slack Block Kit elements for the three feedback buttons."""
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":+1:"},
                    "action_id": f"kb_fb_up:{knowledge_id}:{query_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":-1:"},
                    "action_id": f"kb_fb_down:{knowledge_id}:{query_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":bookmark: Save to KB"},
                    "action_id": f"kb_fb_bookmark:{knowledge_id}:{query_id}",
                },
            ],
        }
    ]


def _parse_action(action_id: str) -> tuple[str, int, str]:
    """Return (kind, knowledge_id, query_id) for ``kb_fb_{kind}:{kid}:{qid}``."""
    head, kid, qid = action_id.split(":", 2)
    kind = head.removeprefix("kb_fb_")
    return kind, int(kid), qid


class FeedbackHandler:
    """Handles upvote / downvote / bookmark button clicks on answer messages."""

    def __init__(self, db, slack_client) -> None:
        self._db = db
        self._slack = slack_client

    async def handle_button(self, *, ack, body: dict) -> None:
        await ack()
        action_id = body["actions"][0]["action_id"]
        kind, knowledge_id, query_id = _parse_action(action_id)
        user_id = body["user"]["id"]
        message_text = (body.get("message") or {}).get("text", "")

        if kind == "up":
            await self._upvote(knowledge_id, user_id, query_id)
        elif kind == "down":
            await self._downvote(knowledge_id, user_id, query_id)
        elif kind == "bookmark":
            await self._bookmark(knowledge_id, user_id, query_id, message_text)
        else:
            logger.warning("unknown feedback kind: %r", kind)

    async def _upvote(self, kid: int, user_id: str, query_id: str) -> None:
        async with self._db.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE org_knowledge SET rank_weight = rank_weight + 1.0 "
                    "WHERE id=$1",
                    kid,
                )
                await conn.execute(
                    "INSERT INTO kb_feedback "
                    "(knowledge_id, user_id, kind, query_text) "
                    "VALUES ($1, $2, 'up', $3)",
                    kid,
                    user_id,
                    query_id,
                )
                await _audit_feedback(conn, user_id, "feedback_up", kid, query_id)

    async def _downvote(self, kid: int, user_id: str, query_id: str) -> None:
        async with self._db.acquire() as conn:
            async with conn.transaction():
                flag_count = await conn.fetchval(
                    "UPDATE org_knowledge SET flag_count = flag_count + 1 "
                    "WHERE id=$1 RETURNING flag_count",
                    kid,
                )
                await conn.execute(
                    "INSERT INTO kb_feedback "
                    "(knowledge_id, user_id, kind, query_text) "
                    "VALUES ($1, $2, 'down', $3)",
                    kid,
                    user_id,
                    query_id,
                )
                await _audit_feedback(conn, user_id, "feedback_down", kid, query_id)

                if flag_count and flag_count > _RE_REVIEW_FLAG_THRESHOLD:
                    row = await conn.fetchrow(
                        "SELECT project_id, title, body, category "
                        "FROM org_knowledge WHERE id=$1",
                        kid,
                    )
                    if row is not None:
                        await conn.execute(
                            """
                            INSERT INTO promotion_candidates
                                (project_id, extracted_from, proposed_title,
                                 proposed_body, proposed_category, sources_json,
                                 confidence, status)
                            VALUES ($1, 'rereview', $2, $3, $4, '[]'::jsonb,
                                    0.5, 'pending')
                            """,
                            row["project_id"],
                            f"re-review: {row['title']}",
                            row["body"],
                            row["category"],
                        )

    async def _bookmark(
        self, kid: int, user_id: str, query_id: str, message_text: str
    ) -> None:
        async with self._db.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT project_id FROM org_knowledge WHERE id=$1", kid
                )
                # Insert the answer text verbatim as a fast-track candidate.
                await conn.execute(
                    """
                    INSERT INTO promotion_candidates
                        (project_id, extracted_from, original_user,
                         proposed_title, proposed_body, proposed_category,
                         sources_json, confidence, status)
                    VALUES ($1, 'bookmark_fast_track', $2, $3, $4, 'howto',
                            '[]'::jsonb, 0.95, 'pending')
                    """,
                    row["project_id"] if row else None,
                    user_id,
                    (message_text[:120] or "bookmarked answer"),
                    message_text or "(no body)",
                )
                await conn.execute(
                    "INSERT INTO kb_feedback "
                    "(knowledge_id, user_id, kind, query_text, answer_text) "
                    "VALUES ($1, $2, 'bookmark', $3, $4)",
                    kid,
                    user_id,
                    query_id,
                    message_text,
                )
                await _audit_feedback(
                    conn, user_id, "feedback_bookmark", kid, query_id
                )


async def _audit_feedback(
    conn, actor: str, action: str, kid: int, query_id: str
) -> None:
    await conn.execute(
        """
        INSERT INTO kb_audit_log
            (actor, action, subject_type, subject_id, metadata)
        VALUES ($1, $2, 'org_knowledge', $3, $4::jsonb)
        """,
        actor,
        action,
        str(kid),
        json.dumps({"query_id": query_id}),
    )


def register_feedback_handlers(app, *, handler: FeedbackHandler) -> None:
    """Register Slack Bolt action handlers for the ``kb_fb_*`` family."""
    @app.action(lambda payload: payload.get("action_id", "").startswith("kb_fb_"))
    async def _on_feedback(ack, body):  # pragma: no cover - bolt wiring
        await handler.handle_button(ack=ack, body=body)
