from __future__ import annotations
import pytest
from breadmind.kb.backfill.cli import build_parser, parse_args, format_dry_run
from breadmind.kb.backfill.base import JobReport, JobProgress
import uuid
from datetime import datetime, timezone


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
