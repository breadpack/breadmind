"""Tests for extraction_triggers (Task 12)."""
from __future__ import annotations

import json as _json
from datetime import datetime, timedelta, timezone

from breadmind.kb.extraction_triggers import (
    is_thread_resolved,
    process_thread_resolved,
)


def _reply(ts: float, user: str = "U1", reactions=None, text: str = "x"):
    return {
        "ts": str(ts),
        "user": user,
        "text": text,
        "reactions": [{"name": n, "count": 1} for n in (reactions or [])],
    }


def test_thread_resolved_white_check_mark():
    msgs = [_reply(1.0, reactions=["white_check_mark"])]
    assert is_thread_resolved(msgs) is True


def test_thread_resolved_thread_closed():
    msgs = [_reply(1.0, reactions=["thread_closed"])]
    assert is_thread_resolved(msgs) is True


def test_thread_not_resolved_active_recent():
    now_ts = datetime.now(timezone.utc).timestamp()
    msgs = [_reply(now_ts - 60)]
    assert is_thread_resolved(msgs) is False


def test_thread_resolved_inactivity_48h():
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=49)).timestamp()
    msgs = [_reply(old_ts)]
    assert is_thread_resolved(msgs) is True


def test_thread_empty_not_resolved():
    assert is_thread_resolved([]) is False


async def test_process_thread_resolved_inserts_candidate(
    db, seeded_project, fake_slack_client, fake_llm_router, fake_sensitive,
    monkeypatch,
):
    fake_llm_router.script = [_json.dumps({"candidates": [{
        "proposed_title": "How we debugged X",
        "proposed_body": "Use strace, not printfs",
        "proposed_category": "howto",
        "confidence": 0.9,
    }]})]

    from breadmind.kb import extraction_triggers as trig
    monkeypatch.setattr(trig, "_build_llm_router", lambda: fake_llm_router)
    monkeypatch.setattr(trig, "_build_sensitive", lambda: fake_sensitive)
    monkeypatch.setattr(trig, "_build_slack_client", lambda: fake_slack_client)
    monkeypatch.setattr(trig, "_build_db", lambda: db)

    # Provide conversations_replies on the fake client
    now_ts = datetime.now(timezone.utc).timestamp()

    async def fake_replies(channel, ts, **kwargs):
        return {
            "ok": True,
            "messages": [
                {
                    "ts": str(now_ts),
                    "user": "U-AUTHOR",
                    "text": "we fixed it",
                    "reactions": [{"name": "white_check_mark", "count": 1}],
                },
            ],
        }

    fake_slack_client.conversations_replies = fake_replies

    result = await process_thread_resolved(
        channel_id="C1",
        thread_ts="1.0",
        project_id=str(seeded_project),
    )
    assert result["candidates_enqueued"] == 1


async def test_personal_nightly_processes_last_24h(
    db, seeded_project, fake_slack_client, fake_llm_router, fake_sensitive,
    monkeypatch,
):
    # Seed v2_episodic_memory with one row within 24h and one older.
    async with db.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS v2_episodic_memory (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                project_id UUID,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            "INSERT INTO v2_episodic_memory (user_id, project_id, content, created_at)"
            " VALUES ('U-MEMBER', $1, 'recent insight', now() - interval '2 hours')",
            seeded_project,
        )
        await conn.execute(
            "INSERT INTO v2_episodic_memory (user_id, project_id, content, created_at)"
            " VALUES ('U-MEMBER', $1, 'old insight', now() - interval '48 hours')",
            seeded_project,
        )

    fake_llm_router.script = [_json.dumps({"candidates": [{
        "proposed_title": "insight",
        "proposed_body": "b",
        "proposed_category": "howto",
        "confidence": 0.9,
    }]})] * 5

    from breadmind.kb import extraction_triggers as trig
    monkeypatch.setattr(trig, "_build_llm_router", lambda: fake_llm_router)
    monkeypatch.setattr(trig, "_build_sensitive", lambda: fake_sensitive)
    monkeypatch.setattr(trig, "_build_slack_client", lambda: fake_slack_client)
    monkeypatch.setattr(trig, "_build_db", lambda: db)

    result = await trig.run_personal_nightly()
    # Only the recent row is processed → one LLM call
    assert len(fake_llm_router.calls) == 1
    assert result["processed"] == 1

    # Cleanup the test-scoped table so other tests don't see it (not strictly
    # necessary per-test DB, but tidy)
    async with db.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS v2_episodic_memory CASCADE")
