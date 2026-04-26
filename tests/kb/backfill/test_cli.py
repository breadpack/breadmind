from __future__ import annotations
import pytest
from breadmind.kb.backfill.cli import build_parser, parse_slack_args


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
