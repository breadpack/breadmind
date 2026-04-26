"""CLI entrypoint: breadmind kb backfill <slack|resume|list|cancel>."""
from __future__ import annotations
import argparse
import uuid
from datetime import datetime, timezone


def _iso_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="breadmind kb backfill")
    sub = p.add_subparsers(dest="subcommand", required=True)

    slack = sub.add_parser("slack", help="Slack backfill")
    slack.add_argument("--org", required=True, type=uuid.UUID)
    slack.add_argument("--channel", required=True, action="append")
    slack.add_argument("--since", required=True, type=_iso_date)
    slack.add_argument("--until", required=True, type=_iso_date)
    slack.add_argument("--token-budget", type=int, default=500_000)
    slack.add_argument(
        "--include-threads", dest="include_threads",
        action="store_true", default=True)
    slack.add_argument(
        "--no-threads", dest="include_threads", action="store_false")
    slack.add_argument("--min-length", type=int, default=5)
    mode = slack.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")

    resume = sub.add_parser("resume", help="Resume a paused/failed job")
    resume.add_argument("job_id", type=uuid.UUID)

    lst = sub.add_parser("list", help="List recent backfill jobs")
    lst.add_argument("--org", required=True, type=uuid.UUID)
    lst.add_argument(
        "--status",
        choices=["running", "paused", "failed", "completed", "cancelled"])

    cancel = sub.add_parser("cancel", help="Cancel a running job")
    cancel.add_argument("job_id", type=uuid.UUID)

    return p


def parse_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)
