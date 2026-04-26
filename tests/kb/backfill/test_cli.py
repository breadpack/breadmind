from __future__ import annotations
import pytest
from breadmind.kb.backfill.cli import build_parser, parse_args, format_dry_run
from breadmind.kb.backfill.base import JobReport, JobProgress
import uuid
from datetime import datetime, timezone


class _FakeSlack:
    """Minimal Slack session for CLI dispatch tests.

    Returns shapes that satisfy SlackBackfillAdapter construction. T16 tests
    monkeypatch ``BackfillRunner.run`` (test 1) or short-circuit before
    runner.run is invoked (test 2), so the session only needs to exist at
    adapter __init__ time.
    """

    async def call(self, method, **params):
        if method == "auth.test":
            return {"ok": True, "team_id": "T1"}
        if method == "conversations.info":
            return {
                "ok": True,
                "channel": {
                    "id": params.get("channel"),
                    "is_archived": False,
                    "name": "general",
                },
            }
        if method == "conversations.members":
            return {"ok": True, "members": [], "response_metadata": {}}
        if method == "conversations.history":
            return {"ok": True, "messages": [], "has_more": False}
        return {"ok": True}


def test_parser_requires_org_and_channel():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["slack"])
    with pytest.raises(SystemExit):
        parser.parse_args(["slack", "--org", "u"])


def test_parse_slack_args_canonicalises():
    parser = build_parser()
    ns = parser.parse_args([
        "slack", "--org", "00000000-0000-0000-0000-000000000001",
        "--channel", "C1", "--channel", "C2",
        "--since", "2026-01-01", "--until", "2026-04-01",
        "--token-budget", "500000", "--dry-run",
    ])
    assert ns.subcommand == "slack"
    assert ns.channel == ["C1", "C2"]
    assert ns.dry_run is True
    assert ns.token_budget == 500_000


def test_parse_slack_args_min_length_and_threads_default():
    parser = build_parser()
    ns = parser.parse_args([
        "slack", "--org", "00000000-0000-0000-0000-000000000001",
        "--channel", "C1", "--since", "2026-01-01",
        "--until", "2026-04-01", "--dry-run"])
    assert ns.include_threads is True  # default
    assert ns.min_length == 5  # default


def test_resume_subcommand_takes_job_id():
    parser = build_parser()
    ns = parser.parse_args(
        ["resume", "00000000-0000-0000-0000-000000000abc"])
    assert ns.subcommand == "resume"


def test_list_filters_status():
    parser = build_parser()
    ns = parser.parse_args([
        "list", "--org", "00000000-0000-0000-0000-000000000001",
        "--status", "running"])
    assert ns.status == "running"


def test_cancel_takes_job_id():
    parser = build_parser()
    ns = parser.parse_args(
        ["cancel", "00000000-0000-0000-0000-000000000abc"])
    assert ns.subcommand == "cancel"


def test_dry_run_output_matches_spec_section_7():
    report = JobReport(
        job_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        org_id=uuid.UUID("8c4f0000-0000-0000-0000-00000000009a"),
        source_kind="slack_msg",
        dry_run=True,
        estimated_count=3512,
        estimated_tokens=412_000,
        indexed_count=0,
        skipped={"signal_filter_short": 812, "signal_filter_bot": 640,
                 "signal_filter_no_engagement": 7103,
                 "signal_filter_mention_only": 414,
                 "acl_lock": 0, "archived": 0, "skipped_existing": 0},
        progress=JobProgress(discovered=12_481, filtered_out=8_969),
        sample_titles=[
            "[#engineering] postgres connection pool tuning recap",
            "[#engineering] re: deploy rollback procedure clarified",
        ],
    )
    ctx = {
        "project_name": "pilot-alpha",
        "team_id": "T012345",
        "team_name": "acme-eng",
        "channels": [("C0123456", "engineering"), ("C0987654", "ops")],
        "since": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "until": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "token_budget": 500_000,
        "monthly_remaining": 7_200_000,
        "monthly_ceiling": 10_000_000,
        "membership_count": 7,
        "membership_snapshotted_at": datetime(
            2026, 4, 26, 13, 42, 11, tzinfo=timezone.utc),
        "thread_root_count": 3_277,
        "top_level_count": 9_204,
    }
    out = format_dry_run(report, ctx)
    assert "Backfill DRY-RUN — Slack" in out
    assert "Org:" in out and "pilot-alpha" in out
    assert "Source:" in out and "slack_msg" in out
    assert "Instance:" in out and "T012345" in out and "acme-eng" in out
    assert "Channels:" in out and "#engineering (C0123456)" in out
    assert "Window:" in out and "2026-01-01T00:00:00Z" in out \
        and "half-open" in out
    assert "Token budget:" in out and "500,000" in out \
        and "7,200,000 / 10,000,000" in out
    assert "Membership lock:" in out and "7 members" in out
    assert "Discovery" in out
    assert "Discovered messages:" in out and "12,481" in out
    assert "top-level:" in out and "9,204" in out
    assert "thread roots:" in out and "3,277" in out
    assert "After signal filter:" in out and "3,512" in out \
        and "drop rate 71.9%" in out
    assert "signal_filter_short:" in out
    assert "Cost estimate" in out
    assert "Estimated tokens (body):" in out and "~412,000" in out \
        and "within budget: yes" in out
    assert "Sample titles" in out
    assert "No data was indexed." in out
    assert "To run for real: re-issue without --dry-run." in out


def test_dry_run_drop_pct_zero_when_no_discovery():
    report = JobReport(
        job_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        org_id=uuid.UUID("8c4f0000-0000-0000-0000-00000000009a"),
        source_kind="slack_msg", dry_run=True,
        estimated_count=0, estimated_tokens=0, indexed_count=0,
        skipped={}, progress=JobProgress(discovered=0, filtered_out=0),
        sample_titles=[],
    )
    ctx = {
        "project_name": "p", "team_id": "T", "team_name": "n",
        "channels": [("C1", "g")],
        "since": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "until": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "token_budget": 100_000, "monthly_remaining": 1, "monthly_ceiling": 2,
        "membership_count": 0,
        "membership_snapshotted_at": datetime(
            2026, 4, 26, tzinfo=timezone.utc),
        "thread_root_count": 0, "top_level_count": 0,
    }
    out = format_dry_run(report, ctx)
    assert "drop rate 0.0%" in out
    assert "Sample titles (0 of 0)" in out


def test_dry_run_within_budget_no_when_over():
    report = JobReport(
        job_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        org_id=uuid.UUID("8c4f0000-0000-0000-0000-00000000009a"),
        source_kind="slack_msg", dry_run=True,
        estimated_count=100, estimated_tokens=999_999_999,
        indexed_count=0, skipped={},
        progress=JobProgress(discovered=200, filtered_out=100),
        sample_titles=[],
    )
    ctx = {
        "project_name": "p", "team_id": "T", "team_name": "n",
        "channels": [("C1", "g")],
        "since": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "until": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "token_budget": 1, "monthly_remaining": 1, "monthly_ceiling": 2,
        "membership_count": 0,
        "membership_snapshotted_at": datetime(
            2026, 4, 26, tzinfo=timezone.utc),
        "thread_root_count": 0, "top_level_count": 0,
    }
    out = format_dry_run(report, ctx)
    assert "within budget: no" in out


# ---------------------------------------------------------------------------
# T16 — main_async dispatch + monthly budget pre-check
# ---------------------------------------------------------------------------


async def test_run_command_dispatches_dry_run(
    monkeypatch, mem_backfill_db, seeded_org, fake_redactor, fake_embedder,
):
    from breadmind.kb.backfill import cli

    captured: dict = {}

    async def fake_run(self, job):
        captured["dry_run"] = job.dry_run
        return JobReport(
            job_id=uuid.uuid4(),
            org_id=job.org_id,
            source_kind=job.source_kind,
            dry_run=job.dry_run,
            estimated_count=0,
            estimated_tokens=0,
            indexed_count=0,
            progress=JobProgress(),
        )

    from breadmind.kb.backfill.runner import BackfillRunner
    monkeypatch.setattr(BackfillRunner, "run", fake_run)
    # Patch budget remaining lookup so test does not require a real DB row.
    async def fake_remaining(*_a, **_kw):
        return 10_000_000
    monkeypatch.setattr(
        "breadmind.kb.backfill.cli._monthly_remaining", fake_remaining)
    argv = [
        "slack", "--org", str(seeded_org), "--channel", "C1",
        "--since", "2026-01-01", "--until", "2026-04-01", "--dry-run",
    ]
    rc = await cli.main_async(
        argv, db=mem_backfill_db, redactor=fake_redactor,
        embedder=fake_embedder, slack_session=_FakeSlack(),
    )
    assert rc == 0
    assert captured["dry_run"] is True


async def test_real_run_aborts_when_monthly_budget_zero(
    monkeypatch, mem_backfill_db, seeded_org, fake_redactor, fake_embedder,
):
    """If OrgMonthlyBudget.remaining() == 0, refuse to start."""
    from breadmind.kb.backfill import cli

    async def zero_remaining(*_a, **_kw):
        return 0
    monkeypatch.setattr(
        "breadmind.kb.backfill.cli._monthly_remaining", zero_remaining)
    argv = [
        "slack", "--org", str(seeded_org), "--channel", "C1",
        "--since", "2026-01-01", "--until", "2026-04-01", "--confirm",
    ]
    rc = await cli.main_async(
        argv, db=mem_backfill_db, redactor=fake_redactor,
        embedder=fake_embedder, slack_session=_FakeSlack(),
    )
    assert rc != 0


# ---------------------------------------------------------------------------
# T17 — resume / list / cancel + mid-run archived handling
#
# These tests use the real ``test_db`` + ``insert_org`` fixtures (from the
# top-level tests/conftest.py) because they exercise actual SQL writes
# against ``kb_backfill_jobs`` via JobCheckpointer. The T16 ``mem_backfill_db``
# stub is unsuitable here — its fetchrow/fetch/execute are passthrough no-ops,
# so resume/list/cancel SQL has nothing to read or update.
# ---------------------------------------------------------------------------


async def test_resume_loads_cursor_and_runs(
    test_db, insert_org, fake_redactor, fake_embedder, monkeypatch,
):
    """Resume: read kb_backfill_jobs row, hand cursor to adapter, re-run."""
    import uuid as _uuid
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill import cli
    from breadmind.kb.backfill.runner import BackfillRunner

    org_id = _uuid.uuid4()
    await insert_org(org_id)
    cp = JobCheckpointer(db=test_db)
    job_id = await cp.start(
        org_id=org_id,
        source_kind="slack_msg",
        source_filter={"channels": ["C1"], "include_threads": True},
        instance_id="T1",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10**9,
        created_by="t",
    )
    await cp.checkpoint(
        job_id=job_id,
        cursor="1735689600000:C1:1.0",
        progress={},
        skipped={},
    )
    await cp.finish(job_id=job_id, status="paused")

    captured: dict = {}

    async def fake_run(self, job):
        # Adapter should have honoured the resume cursor.
        captured["resume_cursor"] = getattr(job, "_resume_cursor", None)
        captured["channels"] = job.source_filter.get("channels")
        from breadmind.kb.backfill.base import JobReport, JobProgress
        return JobReport(
            job_id=_uuid.uuid4(),
            org_id=job.org_id,
            source_kind=job.source_kind,
            dry_run=job.dry_run,
            estimated_count=0,
            estimated_tokens=0,
            indexed_count=0,
            progress=JobProgress(),
        )

    monkeypatch.setattr(BackfillRunner, "run", fake_run)

    argv = ["resume", str(job_id)]
    rc = await cli.main_async(
        argv,
        db=test_db,
        redactor=fake_redactor,
        embedder=fake_embedder,
        slack_session=_FakeSlack(),
    )
    assert rc == 0
    assert captured["resume_cursor"] == "1735689600000:C1:1.0"
    assert captured["channels"] == ["C1"]


async def test_list_prints_recent_jobs(
    test_db, insert_org, capsys,
):
    import uuid as _uuid
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill import cli

    org_id = _uuid.uuid4()
    await insert_org(org_id)
    cp = JobCheckpointer(db=test_db)
    await cp.start(
        org_id=org_id,
        source_kind="slack_msg",
        source_filter={},
        instance_id="T1",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=1,
        created_by="t",
    )
    argv = ["list", "--org", str(org_id)]
    rc = await cli.main_async(
        argv, db=test_db, redactor=None, embedder=None, slack_session=None,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "running" in out
    assert "slack_msg" in out


async def test_cancel_marks_job_cancelled(test_db, insert_org):
    import uuid as _uuid
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill import cli

    org_id = _uuid.uuid4()
    await insert_org(org_id)
    cp = JobCheckpointer(db=test_db)
    job_id = await cp.start(
        org_id=org_id,
        source_kind="slack_msg",
        source_filter={},
        instance_id="T1",
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=1,
        created_by="t",
    )
    argv = ["cancel", str(job_id)]
    rc = await cli.main_async(
        argv, db=test_db, redactor=None, embedder=None, slack_session=None,
    )
    assert rc == 0
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, finished_at FROM kb_backfill_jobs WHERE id=$1",
            job_id,
        )
    assert row["status"] == "cancelled"
    assert row["finished_at"] is not None


async def test_runner_marks_remaining_archived_midrun(
    test_db, insert_org, fake_redactor, fake_embedder,
):
    """ChannelArchived raised mid-discover for one channel must:

    - increment skipped['archived']
    - NOT abort the whole job (other channels still produce items)

    We use a minimal BackfillJob subclass that yields one item from C1, then
    raises ChannelArchived for C2. The runner is expected to catch it,
    record the skip, and continue (or simply finish the run — there are no
    more channels after C2 in this test).
    """
    import uuid as _uuid
    from collections.abc import AsyncIterator

    from breadmind.kb.backfill.base import BackfillItem, BackfillJob
    from breadmind.kb.backfill.runner import BackfillRunner
    from breadmind.kb.backfill.slack import ChannelArchived

    org_id = _uuid.uuid4()
    await insert_org(org_id)

    def _mk_item(i: int) -> BackfillItem:
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return BackfillItem(
            source_kind="slack_msg",
            source_native_id=f"C1:{i}.0",
            source_uri="u",
            source_created_at=ts,
            source_updated_at=ts,
            title=f"t{i}",
            body="hello world",
            author="U1",
        )

    class _FlakyJob(BackfillJob):
        source_kind = "slack_msg"

        async def prepare(self) -> None:
            return None

        async def discover(self) -> AsyncIterator[BackfillItem]:
            # First channel: yield one item normally.
            yield _mk_item(0)
            # Second channel: raise ChannelArchived mid-run. Runner must
            # catch this per-channel and record skipped['archived'].
            raise ChannelArchived("C2")

        def filter(self, item: BackfillItem) -> bool:
            return True

        def instance_id_of(self, source_filter):
            return "T1"

    job = _FlakyJob(
        org_id=org_id,
        source_filter={"channels": ["C1", "C2"]},
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 4, 1, tzinfo=timezone.utc),
        dry_run=False,
        token_budget=10**9,
    )
    runner = BackfillRunner(
        db=test_db, redactor=fake_redactor, embedder=fake_embedder,
    )
    report = await runner.run(job)
    assert report.skipped.get("archived", 0) >= 1
    # Other items still made it through the pipeline.
    assert report.indexed_count >= 1
    assert report.aborted is False
