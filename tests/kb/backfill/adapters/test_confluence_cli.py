"""CLI golden-output + dry-run snapshot tests for Confluence backfill."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from breadmind.kb.backfill.cli import build_parser, format_confluence_dry_run
from breadmind.kb.backfill.base import JobProgress, JobReport

ORG_ID = uuid.UUID("8f3a1b2c-1234-5678-abcd-9e0f1a2b3c4d")


def _make_report(skipped=None, discovered=1247):
    return JobReport(
        job_id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        org_id=ORG_ID,
        source_kind="confluence_page",
        dry_run=True,
        estimated_count=963,
        estimated_tokens=412800,
        indexed_count=0,
        skipped=skipped or {
            "archived": 18,
            "draft": 62,
            "empty_page": 41,
            "attachment_only": 19,
            "acl_lock": 134,
            "restricted": 20,
            "skipped_existing": 10,
        },
        progress=JobProgress(discovered=discovered, filtered_out=284),
    )


class TestConfluenceCliParser:
    def test_space_subcommand_parses(self):
        args = build_parser().parse_args([
            "confluence", "--org", str(ORG_ID),
            "--space", "ENG",
            "--since", "2025-01-01", "--until", "2026-01-01",
            "--dry-run",
        ])
        assert args.subcommand == "confluence"
        assert args.dry_run is True

    def test_page_ids_subcommand_parses(self):
        args = build_parser().parse_args([
            "confluence", "--org", str(ORG_ID),
            "--page-ids", "12345,67890",
            "--since", "2025-01-01", "--until", "2026-01-01",
            "--dry-run",
        ])
        assert args.subcommand == "confluence"
        assert "12345" in args.page_ids

    def test_subtree_subcommand_parses(self):
        args = build_parser().parse_args([
            "confluence", "--org", str(ORG_ID),
            "--subtree", "99999",
            "--since", "2025-01-01", "--until", "2026-01-01",
            "--dry-run",
        ])
        assert args.subcommand == "confluence"
        assert args.subtree == "99999"

    def test_mutually_exclusive_space_and_page_ids(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args([
                "confluence", "--org", str(ORG_ID),
                "--space", "ENG", "--page-ids", "123",
                "--since", "2025-01-01", "--until", "2026-01-01",
                "--dry-run",
            ])

    def test_mutually_exclusive_space_and_subtree(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args([
                "confluence", "--org", str(ORG_ID),
                "--space", "ENG", "--subtree", "999",
                "--since", "2025-01-01", "--until", "2026-01-01",
                "--dry-run",
            ])

    def test_labels_exclude_parses(self):
        args = build_parser().parse_args([
            "confluence", "--org", str(ORG_ID),
            "--space", "ENG",
            "--since", "2025-01-01", "--until", "2026-01-01",
            "--labels-exclude", "draft,wip",
            "--dry-run",
        ])
        assert "draft" in args.labels_exclude
        assert "wip" in args.labels_exclude

    def test_resume_cursor_parses(self):
        args = build_parser().parse_args([
            "confluence", "--org", str(ORG_ID),
            "--space", "ENG",
            "--since", "2025-01-01", "--until", "2026-01-01",
            "--resume", "1748736000000:10001",
            "--dry-run",
        ])
        assert args.resume == "1748736000000:10001"

    def test_reingest_parses(self):
        args = build_parser().parse_args([
            "confluence", "--org", str(ORG_ID),
            "--space", "ENG",
            "--since", "2025-01-01", "--until", "2026-01-01",
            "--reingest", "--dry-run",
        ])
        assert args.reingest is True


class TestFormatConfluenceDryRun:
    def _ctx(self, spaces=None):
        return {
            "org_label": f"pilot-alpha (uuid={ORG_ID})",
            "source_filter": {"kind": "space", "spaces": spaces or ["ENG"]},
            "since": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "until": datetime(2026, 4, 26, tzinfo=timezone.utc),
            "token_budget": 1_000_000,
        }

    def test_header_line_present(self):
        out = format_confluence_dry_run(_make_report(), self._ctx())
        assert "BackfillJob[confluence]" in out

    def test_skip_reasons_alphabetically_ordered(self):
        out = format_confluence_dry_run(_make_report(), self._ctx())
        keys = ["acl_lock", "archived", "attachment_only", "draft", "empty_page",
                "skipped_existing"]
        positions = [out.find(k) for k in keys if k in out]
        assert positions == sorted(positions)

    def test_store_dry_run_label(self):
        out = format_confluence_dry_run(_make_report(), self._ctx())
        assert "DRY-RUN" in out

    def test_token_budget_line(self):
        out = format_confluence_dry_run(_make_report(), self._ctx())
        assert "Token budget" in out

    def test_uses_skipped_existing_not_already_ingested(self):
        """Spec self-review fix: key must be skipped_existing, not already_ingested."""
        out = format_confluence_dry_run(_make_report(), self._ctx())
        assert "skipped_existing" in out
        assert "already_ingested" not in out
