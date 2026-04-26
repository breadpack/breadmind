"""Tests for breadmind kb backfill notion CLI (Tasks 11, 12, 13).

Task 11:
- test_cli_args_parse
- test_cli_org_uuid_validation
- test_cli_default_since_is_last_cursor_or_epoch
- test_cli_exit_codes

Task 12:
- test_dry_run_output_matches_spec

Task 13:
- test_dry_run_exceeds_budget_returns_exit_2
- test_dry_run_exceeds_org_month_ceiling_returns_exit_2
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.kb.backfill.cli import build_parser, format_notion_dry_run


_VALID_ORG = "7c1a5b94-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Task 11: CLI argument parsing
# ---------------------------------------------------------------------------


def test_cli_args_parse():
    p = build_parser()
    args = p.parse_args([
        "notion",
        "--org", _VALID_ORG,
        "--workspace", "pilot-alpha",
        "--since", "2026-01-01",
        "--until", "2026-04-01",
        "--token-budget", "2000000",
        "--dry-run",
    ])
    assert args.subcommand == "notion"
    assert args.org == uuid.UUID(_VALID_ORG)
    assert args.workspace == "pilot-alpha"
    assert args.since == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert args.until == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert args.token_budget == 2_000_000
    assert args.dry_run is True


def test_cli_org_uuid_validation(capsys):
    """--org that is not a valid UUID should cause exit code 2 (argparse error)."""
    p = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        p.parse_args(["notion", "--org", "not-a-uuid", "--workspace", "x", "--dry-run"])
    assert exc_info.value.code != 0


def test_cli_notion_default_since_epoch():
    """When --since is omitted, since defaults to epoch (1970-01-01)."""
    p = build_parser()
    args = p.parse_args([
        "notion",
        "--org", _VALID_ORG,
        "--workspace", "pilot-alpha",
        "--dry-run",
    ])
    assert args.since == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_cli_notion_default_until_is_none():
    """When --until is omitted, until is None (main_async fills in now())."""
    p = build_parser()
    args = p.parse_args([
        "notion",
        "--org", _VALID_ORG,
        "--workspace", "pilot-alpha",
        "--dry-run",
    ])
    assert args.until is None


# ---------------------------------------------------------------------------
# Task 12: dry-run output format
# ---------------------------------------------------------------------------


def _make_fake_report(
    *,
    discovered: int = 1284,
    estimated_count: int = 932,
    estimated_tokens: int = 1_840_000,
    skipped: dict | None = None,
    budget_hit: bool = False,
) -> MagicMock:
    """Build a fake JobReport for dry-run rendering tests."""
    from breadmind.kb.backfill.base import JobProgress
    report = MagicMock()
    report.org_id = uuid.UUID(_VALID_ORG)
    report.source_kind = "notion_page"
    report.dry_run = True
    report.estimated_count = estimated_count
    report.estimated_tokens = estimated_tokens
    report.indexed_count = 0
    report.errors = 0
    report.budget_hit = budget_hit
    report.cursor = None
    prog = JobProgress()
    prog.discovered = discovered
    report.progress = prog
    report.skipped = skipped or {
        "archived": 71,
        "template": 18,
        "empty_page": 201,
        "in_trash": 5,
        "duplicate_body": 57,
        "share_revoked": 0,
        "acl_lock": 0,
        "title_only": 0,
        "oversized": 0,
    }
    return report


def _make_ctx(
    *,
    workspace: str = "pilot-alpha",
    since: datetime | None = None,
    until: datetime | None = None,
    token_budget: int = 2_000_000,
    monthly_remaining: int = 18_400_000,
    monthly_ceiling: int = 20_000_000,
    inline_db_count: int = 14,
    rows_queued: int = 312,
    visible_pages: int = 1284,
) -> dict:
    return {
        "workspace": workspace,
        "since": since or datetime(2026, 1, 1, tzinfo=timezone.utc),
        "until": until or datetime.now(timezone.utc),
        "token_budget": token_budget,
        "monthly_remaining": monthly_remaining,
        "monthly_ceiling": monthly_ceiling,
        "inline_db_count": inline_db_count,
        "rows_queued": rows_queued,
        "visible_pages": visible_pages,
    }


def test_dry_run_output_matches_spec():
    """The dry-run output must include all mandatory spec §7 lines."""
    report = _make_fake_report()
    ctx = _make_ctx()
    output = format_notion_dry_run(report, ctx)

    # Header
    assert "[notion-backfill]" in output
    assert "pilot-alpha" in output
    assert "2026-01-01" in output

    # Discovery counts
    assert "1,284" in output  # discovered pages
    assert "932" in output    # in scope after filter

    # Skipped reasons (must appear even if 0)
    assert "skipped[archived]" in output
    assert "skipped[template]" in output
    assert "skipped[empty_page]" in output
    assert "skipped[in_trash]" in output
    assert "skipped[duplicate_body]" in output
    assert "skipped[share_revoked]" in output

    # Inline databases
    assert "inline databases" in output
    assert "rows queued" in output

    # Token budget section
    assert "estimated tokens" in output
    assert "1,840,000" in output or "1.84M" in output or "1840000" in output

    # Rate limit line
    assert "3 rps" in output

    # Permission lock
    assert "share-in snapshot" in output
    assert "C1" in output

    # Cursor format
    assert "last_edited_time:page_id" in output
    assert "D2" in output

    # Footer
    assert "DRY RUN" in output
    assert "no rows written" in output


def test_dry_run_output_budget_ok_label():
    report = _make_fake_report(estimated_tokens=1_000_000)
    ctx = _make_ctx(token_budget=2_000_000)
    output = format_notion_dry_run(report, ctx)
    assert "[OK]" in output


def test_dry_run_output_budget_exceeded_label():
    report = _make_fake_report(estimated_tokens=3_000_000, budget_hit=True)
    ctx = _make_ctx(token_budget=2_000_000)
    output = format_notion_dry_run(report, ctx)
    assert "[BUDGET EXCEEDED]" in output


# ---------------------------------------------------------------------------
# Task 13: exit codes for budget exceeded
# ---------------------------------------------------------------------------


async def test_dry_run_exceeds_budget_returns_exit_2():
    """dry-run where estimated_tokens > token_budget → exit code 2."""
    from breadmind.kb.backfill.cli_notion import main_async_notion

    report = _make_fake_report(estimated_tokens=3_000_000, budget_hit=False)

    async def fake_monthly_remaining(_db, _org, _ceiling):
        return 20_000_000  # plenty remaining

    with (
        patch("breadmind.kb.backfill.cli_notion.BackfillRunner") as MockRunner,
        patch(
            "breadmind.kb.backfill.cli_notion.NotionBackfillAdapter.prepare",
            new_callable=AsyncMock,
        ),
        patch("breadmind.kb.backfill.cli._monthly_remaining", side_effect=fake_monthly_remaining),
    ):
        instance = MagicMock()
        instance.run = AsyncMock(return_value=report)
        MockRunner.return_value = instance

        code = await main_async_notion(
            [
                "notion",
                "--org", _VALID_ORG,
                "--workspace", "pilot-alpha",
                "--token-budget", "2000000",
                "--dry-run",
            ],
            db=MagicMock(),
            redactor=MagicMock(),
            embedder=MagicMock(),
            monthly_ceiling=20_000_000,
        )

    assert code == 2


async def test_dry_run_exceeds_org_month_ceiling_returns_exit_2():
    """dry-run where tokens would exceed org month ceiling → exit code 2."""
    from breadmind.kb.backfill.cli_notion import main_async_notion

    # estimated_tokens=1M but monthly_remaining=500k → ceiling exceeded
    report = _make_fake_report(estimated_tokens=1_000_000)

    async def fake_monthly_remaining(db, org_id, ceiling):
        return 500_000  # less than estimated_tokens

    with patch("breadmind.kb.backfill.cli_notion.BackfillRunner") as MockRunner:
        instance = MagicMock()
        instance.run = AsyncMock(return_value=report)
        MockRunner.return_value = instance

        with (
            patch(
                "breadmind.kb.backfill.cli_notion.NotionBackfillAdapter.prepare",
                new_callable=AsyncMock,
            ),
            patch(
                "breadmind.kb.backfill.cli._monthly_remaining",
                side_effect=fake_monthly_remaining,
            ),
        ):
            code = await main_async_notion(
                [
                    "notion",
                    "--org", _VALID_ORG,
                    "--workspace", "pilot-alpha",
                    "--token-budget", "2000000",
                    "--dry-run",
                ],
                db=MagicMock(),
                redactor=MagicMock(),
                embedder=MagicMock(),
                monthly_ceiling=20_000_000,
            )

    assert code == 2
