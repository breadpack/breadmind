"""Confluence-specific CLI helpers for `breadmind kb backfill confluence`.

Extracted from :mod:`breadmind.kb.backfill.cli` to match the
``cli_<source>.py`` convention used by the Slack sub-project.

Public surface
--------------
- :func:`add_confluence_subparser` — register ``confluence`` argparse subcommand
- :func:`format_confluence_dry_run` — render a dry-run summary (spec §8)
- :func:`run_confluence` — async dispatcher for the ``confluence`` subcommand
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone


def _iso_date(s: str) -> datetime:
    """Parse a YYYY-MM-DD string into a UTC-aware datetime."""
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def _comma_list(s: str) -> list[str]:
    """Split a comma-separated string into a stripped list."""
    return [x.strip() for x in s.split(",") if x.strip()]


def add_confluence_subparser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    """Register the ``confluence`` subcommand with all spec §7 flags."""
    cf = sub.add_parser("confluence", help="Confluence backfill")
    cf.add_argument("--org", required=True, type=uuid.UUID)

    # Scope flags — mutually exclusive (spec §7)
    scope = cf.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--space", dest="space", action="append", metavar="SPACE_KEY",
        help="Space key(s) to backfill (repeatable)",
    )
    scope.add_argument(
        "--page-ids", dest="page_ids", type=_comma_list, metavar="ID,...",
        help="Comma-separated page IDs to backfill",
    )
    scope.add_argument(
        "--subtree", dest="subtree", metavar="ROOT_PAGE_ID",
        help="Root page ID; backfill the entire subtree",
    )

    cf.add_argument("--since", required=True, type=_iso_date)
    cf.add_argument("--until", required=True, type=_iso_date)
    cf.add_argument("--token-budget", dest="token_budget", type=int, default=500_000)
    cf.add_argument(
        "--labels-exclude", dest="labels_exclude", type=_comma_list,
        metavar="LABEL,...", default=[],
        help="Comma-separated label names to exclude from the CQL query",
    )
    cf.add_argument("--reingest", action="store_true", default=False)
    cf.add_argument(
        "--resume", dest="resume", metavar="CURSOR", default=None,
        help="Resume from a previous partial run cursor (D2 format)",
    )
    cf_mode = cf.add_mutually_exclusive_group(required=True)
    cf_mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    cf_mode.add_argument("--confirm", action="store_true")


# ---------------------------------------------------------------------------
# Dry-run formatter
# ---------------------------------------------------------------------------


def format_confluence_dry_run(report: object, ctx: dict) -> str:  # noqa: ANN001
    """Render a dry-run summary for the Confluence backfill (spec §8).

    Section order: BackfillJob header, source_filter, budget, Discover,
    Filter, Redact, Embed (estimated), Store (DRY-RUN), Token budget,
    Sample skips. Skip keys are alphabetically sorted (self-review fix).
    ``already_ingested`` → ``skipped_existing`` (plan self-review note 1).
    """
    def fmt_int(n: int) -> str:
        return f"{n:,}"

    sf = ctx.get("source_filter", {})
    since = ctx["since"].strftime("%Y-%m-%d")
    until = ctx["until"].strftime("%Y-%m-%d")
    budget = ctx.get("token_budget", 0)
    org_label = ctx.get("org_label", str(report.org_id))  # type: ignore[attr-defined]

    sf_kind = sf.get("kind", "space")
    if sf_kind == "space":
        sf_str = f"space={sf.get('spaces', [])}  since={since}  until={until}"
    elif sf_kind == "page_ids":
        sf_str = f"page_ids={sf.get('ids', [])}  since={since}  until={until}"
    else:
        sf_str = f"subtree={sf.get('root_page_id')}  since={since}  until={until}"

    discovered = report.progress.discovered  # type: ignore[attr-defined]
    keep = report.estimated_count  # type: ignore[attr-defined]
    skip_total = max(0, discovered - keep)
    estimated_chunks = keep * 3  # rough 3 chunks/page estimate

    # Token budget display
    est_tokens = report.estimated_tokens  # type: ignore[attr-defined]
    pct = (est_tokens / budget * 100) if budget else 0.0
    within = "yes" if est_tokens <= budget else "no"

    lines = [
        f"BackfillJob[confluence] org={org_label}",
        f"  source_filter: {sf_str}",
        f"  budget:        token={fmt_int(budget)}  dry_run=ON",
        "",
        f"Discover ............ {fmt_int(discovered)} pages",
        f"Filter ..............   {fmt_int(keep)} keep   /   {fmt_int(skip_total)} skip",
    ]

    # Alphabetically sorted skip keys (spec §8 / self-review fix)
    all_skip_keys = sorted(report.skipped.keys())  # type: ignore[attr-defined]
    for k in all_skip_keys:
        v = report.skipped.get(k, 0)  # type: ignore[attr-defined]
        lines.append(f"  {'+-' if k == all_skip_keys[-1] else '+-'} {k} ........  {fmt_int(v)}")

    est_pii = keep * 13  # rough PII token estimate
    lines += [
        f"Redact ..............   {fmt_int(keep)} pages   (~{fmt_int(est_pii)} PII tokens masked)",
        f"Embed (estimated) ...   {fmt_int(keep)} pages x ~3 chunks"
        f" = {fmt_int(estimated_chunks)} vectors",
        "Store (DRY-RUN) .....     0 rows inserted",
        f"Token budget ........   ~{fmt_int(est_tokens)} / {fmt_int(budget)}"
        f" ({pct:.0f}%)  within budget: {within}",
    ]

    if report.sample_titles:  # type: ignore[attr-defined]
        lines += ["", "Sample skips:"]
        for title in report.sample_titles[:3]:  # type: ignore[attr-defined]
            lines.append(f"  {title}")

    lines += [
        "",
        "Run again without --dry-run to commit.",
        f"JobReport id: {report.job_id}",  # type: ignore[attr-defined]
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Async dispatcher
# ---------------------------------------------------------------------------


async def run_confluence(
    args: object,
    *,
    db: object,
    redactor: object,
    embedder: object,
    vault: object,
    monthly_ceiling: int,
) -> int:
    """Construct a ConfluenceBackfillAdapter, run the job, render output."""
    from breadmind.kb.backfill.adapters.confluence import ConfluenceBackfillAdapter
    from breadmind.kb.backfill.budget import OrgMonthlyBudget
    from breadmind.kb.backfill.checkpoint import JobCheckpointer
    from breadmind.kb.backfill.runner import BackfillRunner
    from datetime import date

    # Inline budget check (avoids circular import with cli._monthly_remaining)
    _budget_obj = OrgMonthlyBudget(db=db, ceiling=monthly_ceiling)
    remaining = await _budget_obj.remaining(
        args.org, period=date.today().replace(day=1)  # type: ignore[attr-defined]
    )
    if getattr(args, "confirm", False) and remaining <= 0:
        print(
            "Per-org monthly token ceiling exhausted; "
            "ask admin to lift before re-running."
        )
        return 3

    # Resolve base_url + credentials_ref from vault / config (stub for now)
    base_url = "https://example.atlassian.net/wiki"  # replaced by config injection
    credentials_ref = f"confluence:org:{args.org}"  # type: ignore[attr-defined]

    job = ConfluenceBackfillAdapter(
        org_id=args.org,  # type: ignore[attr-defined]
        source_filter=args.source_filter,  # type: ignore[attr-defined]
        since=args.since,  # type: ignore[attr-defined]
        until=args.until,  # type: ignore[attr-defined]
        dry_run=args.dry_run,  # type: ignore[attr-defined]
        token_budget=args.token_budget,  # type: ignore[attr-defined]
        base_url=base_url,
        credentials_ref=credentials_ref,
        vault=vault,
        db=db,
    )
    job._reingest = getattr(args, "reingest", False)
    if getattr(args, "resume", None):
        job._resume_cursor = args.resume  # type: ignore[attr-defined]

    org_budget = OrgMonthlyBudget(db=db, ceiling=monthly_ceiling)
    runner = BackfillRunner(
        db=db, redactor=redactor, embedder=embedder, org_budget=org_budget,
        checkpointer=JobCheckpointer(db=db),
    )
    report = await runner.run(job)
    if args.dry_run:  # type: ignore[attr-defined]
        ctx = {
            "org_label": str(args.org),  # type: ignore[attr-defined]
            "source_filter": args.source_filter,  # type: ignore[attr-defined]
            "since": args.since,  # type: ignore[attr-defined]
            "until": args.until,  # type: ignore[attr-defined]
            "token_budget": args.token_budget,  # type: ignore[attr-defined]
        }
        print(format_confluence_dry_run(report, ctx))
    else:
        print(
            f"indexed={report.indexed_count} "  # type: ignore[attr-defined]
            f"errors={report.errors} cursor={report.cursor}"  # type: ignore[attr-defined]
        )
    return 0
