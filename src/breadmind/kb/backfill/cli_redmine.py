"""Redmine-specific CLI formatter and runner for `breadmind kb backfill redmine`.

Split from cli.py to keep each module under 500 LOC.
"""
from __future__ import annotations

from breadmind.kb.backfill.base import JobReport


def format_dry_run_redmine(report: JobReport, ctx: dict) -> str:
    """Render the Redmine dry-run report matching spec §Dry-run Output Example.

    Spec requires section headings in order:
      Discover / Filter / Rows that WOULD be stored / Cost estimate.
    Anchor and journal rows MUST appear on separate lines (parent/child visible).
    """
    def fmt(n: int) -> str:
        return f"{n:,}"

    since = ctx["since"].strftime("%Y-%m-%d")
    until = ctx["until"].strftime("%Y-%m-%d")
    row_counts: dict[str, int] = ctx.get("row_counts") or {}
    issues_fetched = report.progress.discovered
    token_budget = ctx.get("token_budget", 0)
    monthly_remaining = ctx.get("monthly_remaining", 0)
    monthly_ceiling = ctx.get("monthly_ceiling", 0)
    within = "yes" if report.estimated_tokens <= token_budget else "no"

    lines = [
        "Redmine backfill — DRY RUN",
        f"  instance: {ctx.get('instance', '(unset)')}",
        f"  project:  {ctx.get('project', '(unset)')}",
        f"  window:   {since} → {until}",
        "",
        "Discover",
        f"  issues fetched ............ {fmt(issues_fetched)}",
        f"  wiki pages fetched ........  {fmt(row_counts.get('redmine_wiki', 0))}",
        f"  attachments fetched .......  {fmt(row_counts.get('redmine_attachment', 0))}",
        "",
        "Filter (JobReport.skipped — D1 keys)",
        f"  kept issues ...................   {fmt(report.estimated_count)}"
        "   (closed/resolved with description >= 40 chars)",
    ]
    for key in (
        "closed_old",
        "empty_description",
        "auto_generated",
        "metadata_only_journal",
        "private_notes",
        "acl_lock",
    ):
        v = report.skipped.get(key, 0)
        lines.append(f"  {key} ......... {fmt(v)}")
    lines += [
        "",
        "Rows that WOULD be stored (BackfillItem with parent_ref shown for children — D3)",
        f"  redmine_issue        ....   {fmt(row_counts.get('redmine_issue', 0))}"
        "   (parent_ref=None)",
        f"  redmine_journal      ....   {fmt(row_counts.get('redmine_journal', 0))}"
        "   (parent_ref=redmine_issue:<id>, across kept issues)",
        f"  redmine_wiki         ....    {fmt(row_counts.get('redmine_wiki', 0))}"
        "   (parent_ref=None)",
        f"  redmine_attachment   ....     {fmt(row_counts.get('redmine_attachment', 0))}"
        "   (parent_ref=redmine_issue:<id>)",
        f"  {'─' * 37}",
        f"  TOTAL                ....  {fmt(sum(row_counts.values()))}",
        "",
        "Cost estimate",
        f"  embed tokens ..............  ~{fmt(report.estimated_tokens)}"
        f"  (within budget: {within})",
        f"  pgvector rows .............   {fmt(report.estimated_count)}",
        f"  per-org monthly remaining:  {fmt(monthly_remaining)} / {fmt(monthly_ceiling)}",
        "",
        "No changes written. Re-run without --dry-run to commit.",
    ]
    return "\n".join(lines)


async def run_redmine(
    args, *, db, redactor, embedder, vault, monthly_ceiling,
    _monthly_remaining_fn,
) -> int:
    """Construct RedmineBackfillAdapter + runner for Redmine backfill.

    ``_monthly_remaining_fn`` is injected so tests can monkeypatch it
    without coupling to the module-level function in cli.py.
    """
    from datetime import datetime, timedelta, timezone

    from breadmind.kb.backfill.adapters.redmine import RedmineBackfillAdapter
    from breadmind.kb.backfill.adapters.redmine_client import RedmineClient
    from breadmind.kb.backfill.budget import OrgMonthlyBudget
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill.runner import BackfillRunner

    # Resolve since/until with sensible defaults.
    since = args.since
    until = args.until
    if until is None:
        until = datetime.now(timezone.utc)
    if since is None:
        since = until - timedelta(days=90)

    remaining = await _monthly_remaining_fn(db, args.org, monthly_ceiling)
    if args.confirm and remaining <= 0:
        print(
            "Per-org monthly token ceiling exhausted; "
            "ask admin to lift before re-running."
        )
        return 3

    # Resolve vault ref: use explicit --instance or discover the only one.
    vault_ref = args.instance or f"redmine:org:{args.org}"

    client = RedmineClient.from_vault(vault or {}, vault_ref)
    job = RedmineBackfillAdapter(
        client=client,
        org_id=args.org,
        source_filter={
            "project_id": args.project,
            "include": [s.strip() for s in args.include.split(",")],
        },
        since=since,
        until=until,
        dry_run=args.dry_run,
        token_budget=args.token_budget,
        vault=vault,
    )
    if args.resume:
        job._resume_cursor = str(args.resume)

    budget = OrgMonthlyBudget(db=db, ceiling=monthly_ceiling)
    runner = BackfillRunner(
        db=db, redactor=redactor, embedder=embedder, org_budget=budget,
        checkpointer=JobCheckpointer(db=db),
    )
    report = await runner.run(job)
    if args.dry_run:
        ctx = {
            "since": since,
            "until": until,
            "instance": client.base_url + "/",
            "project": f"{args.project}",
            "token_budget": args.token_budget,
            "monthly_remaining": remaining,
            "monthly_ceiling": monthly_ceiling,
            "row_counts": {},
        }
        print(format_dry_run_redmine(report, ctx))
    else:
        print(
            f"indexed={report.indexed_count} "
            f"errors={report.errors} cursor={report.cursor}"
        )
    return 0
