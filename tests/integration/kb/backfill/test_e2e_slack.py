"""End-to-end Slack backfill integration tests (T18).

Run only when ``-m e2e`` is passed: these tests stand up a Postgres
container, run alembic migrations through ``010_kb_backfill``, load the
real fastembed model (first invocation downloads it), and exercise the
full ``SlackBackfillAdapter -> BackfillRunner`` pipeline against a fake
Slack session pre-seeded with the spec §10 fixture mix.

Two scenarios:

1. ``test_e2e_200_messages_two_channels_indexes_post_filter`` — covers
   the "filter applies, embed runs, ``org_knowledge`` rows land with
   matching counts" happy path.
2. ``test_e2e_resume_after_kill_no_duplicates`` — covers the
   ``uq_org_knowledge_source_native`` dedup contract: a flaky embedder
   raises mid-run, a fresh ``BackfillRunner`` restarts the job, and the
   final row count contains no duplicates.

The fixtures live in ``conftest.py`` (testcontainers + real_redactor +
fastembed-padded real_embedder + 220-message FakeSlackSession).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from breadmind.kb.backfill.budget import OrgMonthlyBudget
from breadmind.kb.backfill.checkpoint import JobCheckpointer
from breadmind.kb.backfill.runner import BackfillRunner
from breadmind.kb.backfill.slack import SlackBackfillAdapter

from tests.integration.kb.backfill.conftest import _last_cursor_for_org

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_e2e_200_messages_two_channels_indexes_post_filter(
    testcontainers_pg_with_010,
    seeded_org,
    real_redactor,
    real_embedder,
    fake_slack_with_200_messages,
    fixture_vault,
):
    """Full pipeline indexes only post-filter signal-passing messages.

    The 220-message mix (70 short + 50 bot + 30 zero-engagement +
    50 signal-passing + 20 mention-only) survives the
    :meth:`SlackBackfillAdapter.filter` gate as exactly the 50 signal-
    passing items, satisfying the spec §10 ``50 <= indexed_count <= 80``
    bound (extra room reserved for thread roll-ups should the fixture
    grow them later). The ``org_knowledge`` row count is asserted equal
    to ``report.indexed_count`` so the runner's accounting matches the DB.
    """
    job = SlackBackfillAdapter(
        org_id=seeded_org,
        source_filter={"channels": ["C1", "C2"], "include_threads": True},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10**9,
        vault=fixture_vault,
        credentials_ref="slack:e2e",
        session=fake_slack_with_200_messages,
    )
    runner = BackfillRunner(
        db=testcontainers_pg_with_010,
        redactor=real_redactor,
        embedder=real_embedder,
        # ``OrgMonthlyBudget`` is not currently consulted by the runner
        # (T7-T9 wired the field but charge() is invoked elsewhere in
        # spec §4); passing it here matches the plan's contract for the
        # day the gate is wired in.
        org_budget=OrgMonthlyBudget(
            db=testcontainers_pg_with_010, ceiling=10**9
        ),
    )
    report = await runner.run(job)

    # Spec §10: exactly the 50 signal-passing items survive filter; the
    # band leaves headroom for thread roll-ups (currently zero in the
    # fixture). ``aborted/budget_hit`` must be clean for the happy path.
    assert 50 <= report.indexed_count <= 80, (
        f"indexed_count={report.indexed_count} out of [50, 80]; "
        f"skipped={report.skipped}, errors={report.errors}"
    )
    assert report.aborted is False
    assert report.budget_hit is False

    # DB-side ground truth: org_knowledge row count for this org's
    # slack_msg rows must match the runner's reported indexed_count.
    rows = await testcontainers_pg_with_010.fetch(
        "SELECT COUNT(*) AS c FROM org_knowledge "
        "WHERE project_id=$1 AND source_kind='slack_msg'",
        seeded_org,
    )
    assert rows[0]["c"] == report.indexed_count

    # Sanity: the filter rejected the four non-signal categories. The exact
    # bucket counts are stable (70 + 50 + 30 + 20 = 170 dropped).
    skipped = report.skipped
    assert skipped.get("signal_filter_short", 0) == 70
    assert skipped.get("signal_filter_bot", 0) == 50
    assert skipped.get("signal_filter_no_engagement", 0) == 30
    assert skipped.get("signal_filter_mention_only", 0) == 20


async def test_e2e_resume_after_kill_no_duplicates(
    testcontainers_pg_with_010,
    seeded_org,
    real_redactor,
    flaky_embedder_at_73,
    real_embedder,
    fake_slack_with_200_messages,
    fixture_vault,
):
    """Resume after a transient embed failure produces zero duplicate rows.

    ``flaky_embedder_at_73`` raises once on its 73rd ``encode()`` call
    (counted across **all** discover items, not just signal-passing — so
    it lands inside the long stretch of short / bot messages). The runner
    accounts that as ``progress.errors+=1`` and continues; the abort
    threshold (>10% AND ≥200 discovered) is never hit on a single
    failure. A second ``BackfillRunner`` then picks up from the persisted
    cursor with a healthy embedder, and the unique index
    ``uq_org_knowledge_source_native`` (migration 010) prevents any row
    that was already stored from re-inserting.
    """
    db = testcontainers_pg_with_010
    cp1 = JobCheckpointer(db=db)

    job = SlackBackfillAdapter(
        org_id=seeded_org,
        source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10**9,
        vault=fixture_vault,
        credentials_ref="slack:e2e",
        session=fake_slack_with_200_messages,
    )
    runner = BackfillRunner(
        db=db,
        redactor=real_redactor,
        embedder=flaky_embedder_at_73,
        checkpointer=cp1,
    )
    # The runner now swallows per-item errors and returns a partial report
    # rather than raising (T9 review fix); a try/except is harmless.
    try:
        await runner.run(job)
    except Exception:
        pass

    # Resume with a fresh adapter + a healthy embedder.
    job2 = SlackBackfillAdapter(
        org_id=seeded_org,
        source_filter={"channels": ["C1"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10**9,
        vault=fixture_vault,
        credentials_ref="slack:e2e",
        session=fake_slack_with_200_messages,
    )
    job2._resume_cursor = await _last_cursor_for_org(db, seeded_org)
    cp2 = JobCheckpointer(db=db)
    runner2 = BackfillRunner(
        db=db,
        redactor=real_redactor,
        embedder=real_embedder,
        checkpointer=cp2,
    )
    await runner2.run(job2)

    # Dedup contract: the unique index forbids duplicates regardless of
    # whether the resume cursor rewound past already-stored items.
    dup_rows = await db.fetch(
        "SELECT source_native_id, COUNT(*) AS c FROM org_knowledge "
        "WHERE project_id=$1 GROUP BY source_native_id HAVING COUNT(*)>1",
        seeded_org,
    )
    assert dup_rows == []
