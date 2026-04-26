"""CLI entrypoint: breadmind kb backfill <slack|resume|list|cancel>."""
from __future__ import annotations
import argparse
import uuid
from datetime import date, datetime, timezone

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


# ---------------------------------------------------------------------------
# T16 — main_async dispatcher + monthly budget pre-check.
#
# ``_monthly_remaining`` is module-level so tests can monkeypatch it without
# constructing a real OrgMonthlyBudget. ``_run_resume`` / ``_run_list`` /
# ``_run_cancel`` are intentional stubs — T17 wires them to JobCheckpointer.
# ---------------------------------------------------------------------------


async def _monthly_remaining(db, org_id: uuid.UUID, ceiling: int) -> int:
    """Return per-org remaining tokens for the current calendar month.

    Thin wrapper over :class:`OrgMonthlyBudget.remaining` so the budget
    pre-check in :func:`_run_slack` is monkeypatchable from tests without
    needing a real DB row.
    """
    from breadmind.kb.backfill.budget import OrgMonthlyBudget
    budget = OrgMonthlyBudget(db=db, ceiling=ceiling)
    return await budget.remaining(
        org_id, period=date.today().replace(day=1))


async def main_async(
    argv: list[str], *, db, redactor, embedder, slack_session,
    vault=None, monthly_ceiling: int = 10_000_000,
) -> int:
    """Async entrypoint for `breadmind kb backfill ...`.

    Returns process exit code (0 on success, non-zero on usage / budget
    refusal). Resume / list / cancel paths are T17.
    """
    args = build_parser().parse_args(argv)
    if args.subcommand == "slack":
        return await _run_slack(
            args, db=db, redactor=redactor, embedder=embedder,
            slack_session=slack_session, vault=vault,
            monthly_ceiling=monthly_ceiling)
    if args.subcommand == "resume":
        return await _run_resume(
            args.job_id, db=db, redactor=redactor, embedder=embedder,
            slack_session=slack_session, vault=vault)
    if args.subcommand == "list":
        return await _run_list(args, db=db)
    if args.subcommand == "cancel":
        return await _run_cancel(args.job_id, db=db)
    return 2


async def _run_slack(
    args, *, db, redactor, embedder, slack_session, vault, monthly_ceiling,
) -> int:
    """Construct adapter + runner, run the job, render dry-run output."""
    from breadmind.kb.backfill.budget import OrgMonthlyBudget
    from breadmind.kb.backfill.runner import BackfillRunner
    from breadmind.kb.backfill.slack import SlackBackfillAdapter

    # Spec §11 P1: per-org monthly ceiling pre-check. We only refuse a
    # real run; dry-run is allowed even when the ceiling is exhausted so
    # operators can still inspect the discovery/cost report.
    remaining = await _monthly_remaining(db, args.org, monthly_ceiling)
    if args.confirm and remaining <= 0:
        print(
            "Per-org monthly token ceiling exhausted; "
            "ask admin to lift before re-running."
        )
        return 3

    job = SlackBackfillAdapter(
        org_id=args.org,
        source_filter={
            "channels": args.channel,
            "include_threads": args.include_threads,
        },
        since=args.since,
        until=args.until,
        dry_run=args.dry_run,
        token_budget=args.token_budget,
        config={"min_length": args.min_length},
        vault=vault,
        credentials_ref=f"slack:org:{args.org}",
        session=slack_session,
    )
    budget = OrgMonthlyBudget(db=db, ceiling=monthly_ceiling)
    runner = BackfillRunner(
        db=db, redactor=redactor, embedder=embedder, org_budget=budget,
    )
    report = await runner.run(job)
    if args.dry_run:
        ctx = await _build_dry_run_ctx(
            args, job, report, remaining, monthly_ceiling)
        print(format_dry_run(report, ctx))
    else:
        print(
            f"indexed={report.indexed_count} "
            f"errors={report.errors} cursor={report.cursor}"
        )
    return 0


async def _run_resume(
    job_id, *, db, redactor, embedder, slack_session, vault,
) -> int:
    """Resume a paused/failed job. Implemented in T17."""
    raise NotImplementedError("Resume is implemented in T17")


async def _run_list(args, *, db) -> int:
    """List recent backfill jobs. Implemented in T17."""
    raise NotImplementedError("List is implemented in T17")


async def _run_cancel(job_id, *, db) -> int:
    """Cancel a running job. Implemented in T17."""
    raise NotImplementedError("Cancel is implemented in T17")


async def _build_dry_run_ctx(
    args, job, report: JobReport, remaining: int, monthly_ceiling: int,
) -> dict:
    """Best-effort context for the dry-run formatter.

    T16 wires what is reachable from prepare()/runner state. T17 may enrich
    (e.g., split top_level vs thread_root counts properly).
    """
    snapshot_at = report.started_at or datetime.now(timezone.utc)
    return {
        "project_name": getattr(args, "project_name", "(unset)"),
        "team_id": job._team_id or "(unset)",
        "team_name": "(unset)",
        "channels": [
            (cid, job._channel_names.get(cid, cid)) for cid in args.channel
        ],
        "since": args.since,
        "until": args.until,
        "token_budget": args.token_budget,
        "monthly_remaining": remaining,
        "monthly_ceiling": monthly_ceiling,
        "membership_count": len(job._membership_snapshot),
        "membership_snapshotted_at": snapshot_at,
        "thread_root_count": 0,
        "top_level_count": report.progress.discovered,
    }
