"""CLI entrypoint: breadmind kb backfill <slack|resume|list|cancel|redmine>."""
from __future__ import annotations
import argparse
import uuid
from datetime import date, datetime, timezone

from breadmind.kb.backfill.base import JobReport
from breadmind.kb.backfill.cli_redmine import run_redmine


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
    # T16 review #1: project-name surfaces honestly in dry-run output. Until
    # we have an org→project lookup wired, accept it as a CLI flag so the
    # formatter doesn't always print "(unset)".
    slack.add_argument("--project-name", dest="project_name", default="(unset)")
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

    redmine = sub.add_parser("redmine", help="Redmine backfill")
    redmine.add_argument("--org", required=True, type=uuid.UUID)
    redmine.add_argument("--project", required=True)
    redmine.add_argument("--instance", default=None)
    redmine.add_argument("--since", required=False, type=_iso_date, default=None)
    redmine.add_argument(
        "--until", required=False, type=_iso_date,
        default=None,
    )
    redmine.add_argument(
        "--include", default="issues,wiki",
        help="Comma-separated list of: issues, wiki, attachments",
    )
    redmine.add_argument("--token-budget", dest="token_budget",
                         type=int, default=500_000)
    redmine.add_argument("--resume", default=None, type=uuid.UUID)
    redmine_mode = redmine.add_mutually_exclusive_group(required=True)
    redmine_mode.add_argument("--dry-run", action="store_true")
    redmine_mode.add_argument("--confirm", action="store_true")

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
    if args.subcommand == "redmine":
        return await run_redmine(
            args, db=db, redactor=redactor, embedder=embedder,
            vault=vault, monthly_ceiling=monthly_ceiling,
            _monthly_remaining_fn=_monthly_remaining)
    return 2


async def _run_slack(
    args, *, db, redactor, embedder, slack_session, vault, monthly_ceiling,
) -> int:
    """Construct adapter + runner, run the job, render dry-run output."""
    from breadmind.kb.backfill.budget import OrgMonthlyBudget
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
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
        checkpointer=JobCheckpointer(db=db),
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
    """Resume a paused/failed Slack backfill job from its last cursor.

    Reads the kb_backfill_jobs row, reconstructs the SlackBackfillAdapter
    with the same source_filter / window / token_budget, primes
    ``adapter._resume_cursor`` so ``discover()`` rewinds the first channel's
    ``oldest=`` to the persisted cursor, and re-invokes the runner.

    Returns:
        - 0 on successful resume completion
        - 0 (no-op print) when row is dry-run (resume of a dry-run is meaningless)
        - 4 when row is missing
    """
    import json
    row = await db.fetchrow(
        "SELECT id, org_id, source_kind, source_filter, instance_id, "
        "since_ts, until_ts, dry_run, token_budget, last_cursor "
        "FROM kb_backfill_jobs WHERE id=$1",
        job_id,
    )
    if row is None:
        print(f"job {job_id} not found")
        return 4
    if row["dry_run"]:
        print("dry-run resume is a no-op")
        return 0
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill.runner import BackfillRunner
    from breadmind.kb.backfill.slack import SlackBackfillAdapter

    sf = row["source_filter"]
    if isinstance(sf, str):
        sf = json.loads(sf)
    job = SlackBackfillAdapter(
        org_id=row["org_id"],
        source_filter=sf,
        since=row["since_ts"],
        until=row["until_ts"],
        dry_run=False,
        token_budget=row["token_budget"],
        vault=vault,
        credentials_ref=f"slack:org:{row['org_id']}",
        session=slack_session,
    )
    # Adapter honours this in discover(): first channel uses
    # _cursor_to_oldest(_resume_cursor) instead of since_ts.
    job._resume_cursor = row["last_cursor"]
    await BackfillRunner(
        db=db, redactor=redactor, embedder=embedder,
        checkpointer=JobCheckpointer(db=db),
    ).run(job)
    return 0


async def _run_list(args, *, db) -> int:
    """Print the 50 most-recent kb_backfill_jobs rows for ``--org``.

    Optional ``--status`` filters by terminal status. Output is a fixed-
    column ASCII table (no JSON / no rich formatting) so operators can
    grep / awk it the same way as `kubectl get`.
    """
    sql = (
        "SELECT id, source_kind, status, started_at "
        "FROM kb_backfill_jobs WHERE org_id=$1"
    )
    params: list = [args.org]
    if args.status:
        sql += " AND status=$2"
        params.append(args.status)
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = await db.fetch(sql, *params)
    for row in rows:
        print(
            f"{row['id']}  {row['source_kind']:<12}  "
            f"{row['status']:<10}  {row['started_at']}"
        )
    return 0


async def _run_cancel(job_id, *, db) -> int:
    """Mark a running/paused job as cancelled and stamp finished_at.

    The WHERE clause is permissive (running OR paused) so this is a
    no-op against already-terminal rows — useful for idempotent retries
    from operators.
    """
    await db.execute(
        "UPDATE kb_backfill_jobs SET status='cancelled', finished_at=now() "
        "WHERE id=$1 AND status IN ('running','paused')",
        job_id,
    )
    return 0


async def _build_dry_run_ctx(
    args, job, report: JobReport, remaining: int, monthly_ceiling: int,
) -> dict:
    """Best-effort context for the dry-run formatter.

    T16 wires what is reachable from prepare()/runner state. T17:
      - read job state via :meth:`SlackBackfillAdapter.prepare_summary`
        instead of poking private attrs (review item 2)
      - use ``args.project_name`` honestly (review item 1)
      - top_level / thread_root split is still rough; left for T18 e2e.
    """
    snapshot_at = report.started_at or datetime.now(timezone.utc)
    summary = job.prepare_summary() if hasattr(job, "prepare_summary") else {}
    team_id = summary.get("team_id") or "(unset)"
    channel_names: dict = summary.get("channel_names") or {}
    membership_count = summary.get("membership_count", 0)
    return {
        "project_name": getattr(args, "project_name", "(unset)"),
        "team_id": team_id,
        "team_name": "(unset)",
        "channels": [
            (cid, channel_names.get(cid, cid)) for cid in args.channel
        ],
        "since": args.since,
        "until": args.until,
        "token_budget": args.token_budget,
        "monthly_remaining": remaining,
        "monthly_ceiling": monthly_ceiling,
        "membership_count": membership_count,
        "membership_snapshotted_at": snapshot_at,
        "thread_root_count": 0,
        "top_level_count": report.progress.discovered,
    }
