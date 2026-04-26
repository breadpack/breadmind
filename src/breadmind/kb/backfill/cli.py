"""CLI entrypoint: breadmind kb backfill <slack|resume|list|cancel>."""
from __future__ import annotations
import argparse
import uuid
from datetime import datetime, timezone

from breadmind.kb.backfill.base import JobReport


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


def format_dry_run(report: JobReport, ctx: dict) -> str:
    def fmt_int(n: int) -> str:
        return f"{n:,}"
    since = ctx["since"].strftime("%Y-%m-%dT%H:%M:%SZ")
    until = ctx["until"].strftime("%Y-%m-%dT%H:%M:%SZ")
    drop = max(0, report.progress.discovered - report.estimated_count)
    drop_pct = (drop / report.progress.discovered * 100
                if report.progress.discovered else 0.0)
    within = "yes" if report.estimated_tokens <= ctx["token_budget"] \
        else "no"
    channels_line = ", ".join(
        f"#{name} ({cid})" for cid, name in ctx["channels"])
    lines = [
        "Backfill DRY-RUN — Slack",
        "========================",
        f"Org:             {report.org_id} (project: {ctx['project_name']})",
        f"Source:          {report.source_kind}",
        f"Instance:        {ctx['team_id']} (workspace {ctx['team_name']})",
        f"Channels:        {channels_line}",
        f"Window:          {since} → {until}  "
        "(filter: source_updated_at, half-open)",
        f"Token budget:    {fmt_int(ctx['token_budget'])}  (job)  /  "
        f"per-org monthly remaining: {fmt_int(ctx['monthly_remaining'])} "
        f"/ {fmt_int(ctx['monthly_ceiling'])}",
        f"Membership lock: {ctx['membership_count']} members snapshotted "
        f"at {ctx['membership_snapshotted_at'].strftime('%Y-%m-%dT%H:%M:%SZ')}"
        " (per-item ACL: label-only)",
        "",
        "Discovery",
        "---------",
        f"Discovered messages:        {fmt_int(report.progress.discovered)}",
        f"  - top-level:               {fmt_int(ctx['top_level_count'])}",
        f"  - thread roots:            {fmt_int(ctx['thread_root_count'])}",
        f"After signal filter:         {fmt_int(report.estimated_count)}"
        f"   (drop rate {drop_pct:.1f}%)",
        "Skipped (by reason)",
    ]
    for k in ("signal_filter_short", "signal_filter_bot",
             "signal_filter_no_engagement", "signal_filter_mention_only",
             "acl_lock", "archived", "skipped_existing"):
        v = report.skipped.get(k, 0)
        comment = "  (dry-run does not touch DB)" \
            if k == "skipped_existing" else ""
        lines.append(f"  - {k}: {fmt_int(v)}{comment}")
    lines += [
        "",
        "Cost estimate",
        "-------------",
        f"Estimated tokens (body):    ~{fmt_int(report.estimated_tokens)}"
        f"   (within budget: {within})",
        f"Estimated embeddings:        {fmt_int(report.estimated_count)}",
        f"Estimated DB rows:           {fmt_int(report.estimated_count)} "
        f"org_knowledge  (kb_sources rows deferred — schema/writer not yet wired)",
        "",
    ]
    shown_titles = report.sample_titles[:10]
    lines += [
        f"Sample titles ({len(shown_titles)} of {fmt_int(report.estimated_count)})",
        "----------------------------",
    ]
    for t in shown_titles:
        lines.append(f"  {t}")
    lines += ["", "No data was indexed.",
              "To run for real: re-issue without --dry-run."]
    return "\n".join(lines)
