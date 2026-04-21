"""Extraction triggers: Slack thread resolution + personal-KB nightly cron."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_RESOLVED_REACTIONS = frozenset({"white_check_mark", "thread_closed", "heavy_check_mark"})
_INACTIVITY_HOURS = 48


def is_thread_resolved(messages: list[dict]) -> bool:
    """Heuristic for a Slack thread being "resolved" per spec §6.2 trigger A.

    Resolved when:
      - any message carries a resolution reaction
        (``white_check_mark``, ``thread_closed``, ``heavy_check_mark``), OR
      - the most-recent message is older than ``_INACTIVITY_HOURS``.

    Returns ``False`` for an empty list or when all ``ts`` parse to ``0``.
    """
    if not messages:
        return False

    for msg in messages:
        for reaction in msg.get("reactions", []) or []:
            if reaction.get("name") in _RESOLVED_REACTIONS:
                return True

    # Inactivity: last message older than _INACTIVITY_HOURS
    last_ts = max((float(m.get("ts", 0)) for m in messages), default=0.0)
    if last_ts == 0.0:
        return False
    last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
    if datetime.now(timezone.utc) - last_dt > timedelta(hours=_INACTIVITY_HOURS):
        return True
    return False


# ── Injection seams (overridable from tests / worker bootstrap) ────────
def _build_llm_router() -> Any:
    try:
        from breadmind.llm.router import LLMRouter
        return LLMRouter.default()
    except (ImportError, AttributeError):
        return None


def _build_sensitive() -> Any:
    from breadmind.kb.sensitive import SensitiveClassifier
    return SensitiveClassifier()


def _build_slack_client() -> Any:
    from breadmind.tasks import worker as worker_mod
    return getattr(worker_mod, "_slack_client", None)


def _build_db() -> Any:
    from breadmind.tasks import worker as worker_mod
    return getattr(worker_mod, "_db", None)


# ── Trigger A: resolved Slack thread ──────────────────────────────────
async def process_thread_resolved(
    channel_id: str,
    thread_ts: str,
    project_id: str,
) -> dict[str, Any]:
    """Fetch a thread, extract knowledge candidates, enqueue for review.

    Returns a dict with one of:
      - ``{"candidates_enqueued": N}`` on success
      - ``{"skipped": "..."}`` when the project is paused or thread not resolved
      - ``{"error": "..."}`` when db/slack are unavailable or the fetch fails
    """
    from breadmind.kb.extractor import KnowledgeExtractor
    from breadmind.kb.review_dispatcher import is_extraction_paused
    from breadmind.kb.review_queue import ReviewQueue
    from breadmind.kb.types import SourceMeta

    db = _build_db()
    slack = _build_slack_client()
    if db is None or slack is None:
        return {"error": "db or slack unavailable"}

    pid_uuid = UUID(project_id)
    if await is_extraction_paused(db, pid_uuid):
        return {"skipped": "extraction paused for project"}

    try:
        resp = await slack.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = resp.get("messages", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("thread fetch failed: %s", exc)
        return {"error": f"thread fetch failed: {exc}"}

    if not is_thread_resolved(messages):
        return {"skipped": "thread not resolved"}

    content = "\n".join(
        f"<@{m.get('user', '?')}>: {m.get('text', '')}" for m in messages
    )
    first_user = messages[0].get("user") if messages else None
    meta = SourceMeta(
        source_type="slack_msg",
        source_uri=f"slack://thread/{channel_id}/{thread_ts}",
        source_ref=thread_ts,
        original_user=first_user,
        project_id=pid_uuid,
        extracted_from="slack_thread_resolved",
    )

    extractor = KnowledgeExtractor(_build_llm_router(), _build_sensitive())
    candidates = await extractor.extract(content, meta)

    queue = ReviewQueue(db, slack)
    count = 0
    for c in candidates:
        await queue.enqueue(c)
        count += 1
    return {"candidates_enqueued": count}


# ── Trigger B: nightly personal-KB sweep ──────────────────────────────
async def run_personal_nightly() -> dict[str, Any]:
    """Process personal episodic memory added in the last 24h."""
    from breadmind.kb.extractor import KnowledgeExtractor
    from breadmind.kb.review_dispatcher import is_extraction_paused
    from breadmind.kb.review_queue import ReviewQueue
    from breadmind.kb.types import SourceMeta

    db = _build_db()
    slack = _build_slack_client()
    if db is None or slack is None:
        return {"error": "db or slack unavailable", "processed": 0}

    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, project_id, content
            FROM v2_episodic_memory
            WHERE created_at > now() - interval '24 hours'
              AND project_id IS NOT NULL
            ORDER BY created_at ASC
            """
        )

    extractor = KnowledgeExtractor(_build_llm_router(), _build_sensitive())
    queue = ReviewQueue(db, slack)
    processed = 0
    enqueued = 0

    for r in rows:
        pid = r["project_id"]
        if await is_extraction_paused(db, pid):
            continue
        meta = SourceMeta(
            source_type="personal_kb",
            source_uri=f"episodic://{r['id']}",
            source_ref=str(r["id"]),
            original_user=r["user_id"],
            project_id=pid,
            extracted_from="personal_nightly",
        )
        try:
            cands = await extractor.extract(r["content"], meta)
        except Exception as exc:  # noqa: BLE001
            logger.warning("personal nightly extraction failed for row %s: %s",
                           r["id"], exc)
            continue
        for c in cands:
            await queue.enqueue(c)
            enqueued += 1
        processed += 1

    return {"processed": processed, "enqueued": enqueued}
