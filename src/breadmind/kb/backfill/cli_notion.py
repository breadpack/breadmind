"""Notion CLI sub-command: `breadmind kb backfill notion`.

Spec: docs/superpowers/specs/2026-04-26-backfill-notion-design.md §8
Plan: docs/superpowers/plans/2026-04-26-backfill-notion.md Tasks 11-13

Separated from cli.py to keep each file ≤ 500 LOC (project convention).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from breadmind.kb.backfill.base import JobReport
from breadmind.kb.backfill.runner import BackfillRunner
from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter


# ---------------------------------------------------------------------------
# Dry-run text renderer (spec §7)
# ---------------------------------------------------------------------------


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _fmt_tokens(n: int) -> str:
    """Human-readable token count (e.g. 1.84M)."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def format_notion_dry_run(report: JobReport, ctx: dict[str, Any]) -> str:
    """Render the spec §7 dry-run text block.

    Args:
        report: JobReport from BackfillRunner.run(adapter).
        ctx: Dict with keys:
            workspace, since, until, token_budget,
            monthly_remaining, monthly_ceiling,
            inline_db_count, rows_queued, visible_pages.
    """
    workspace = ctx.get("workspace", "(unset)")
    since_str = ctx["since"].strftime("%Y-%m-%d")
    until = ctx.get("until") or datetime.now(timezone.utc)
    until_str = until.strftime("%Y-%m-%d") if ctx.get("until") else "now"

    discovered = report.progress.discovered
    in_scope = report.estimated_count
    est_tokens = report.estimated_tokens
    token_budget = ctx["token_budget"]
    monthly_remaining = ctx.get("monthly_remaining", 0)
    monthly_ceiling = ctx.get("monthly_ceiling", 0)
    tokens_used_after = monthly_ceiling - monthly_remaining + est_tokens
    inline_db_count = ctx.get("inline_db_count", 0)
    rows_queued = ctx.get("rows_queued", 0)
    visible_pages = ctx.get("visible_pages", discovered)

    # Budget check
    budget_ok = est_tokens <= token_budget and tokens_used_after <= monthly_ceiling
    budget_label = "[OK]" if budget_ok else "[BUDGET EXCEEDED]"

    # Skipped lines (always show, even if 0)
    skipped = report.skipped or {}
    skip_keys = ["archived", "template", "empty_page", "in_trash", "duplicate_body",
                 "share_revoked", "acl_lock", "title_only", "oversized"]

    # Estimated metrics
    avg_chunk_tokens = 512
    est_chunks = max(1, est_tokens // avg_chunk_tokens)
    embed_cost = est_chunks * 0.02 / 1000  # text-embedding-3-small $0.02/M tokens
    wall_clock_min = est_chunks / (3 * 60)  # 3 rps, 1 block call per chunk approx

    lines = [
        f"[notion-backfill] org={str(report.org_id)[:8]} workspace={workspace} "
        f"since={since_str} until={until_str}",
        "[notion-backfill] discover via Notion search ...",
        "",
        f"  discovered pages          : {_fmt_int(discovered)}",
        f"  in scope after filter     : {_fmt_int(in_scope):>5}",
    ]
    for key in skip_keys:
        v = skipped.get(key, 0)
        padding = max(0, 20 - len(key))
        lines.append(f"    skipped[{key}]" + " " * padding + f": {_fmt_int(v):>6}")
    lines += [
        f"  inline databases          : {_fmt_int(inline_db_count):>5}  "
        f"(rows queued: {_fmt_int(rows_queued)})",
        "",
        f"  estimated tokens (input)  : {_fmt_tokens(est_tokens)}"
        f"  (run budget={_fmt_tokens(token_budget)}, "
        f"org month ceiling={_fmt_tokens(monthly_ceiling - monthly_remaining)} "
        f"of {_fmt_tokens(monthly_ceiling)})  {budget_label}",
        f"  estimated chunks          : {_fmt_int(est_chunks)}",
        f"  estimated embed cost      : ~${embed_cost:.2f} "
        "(text-embedding-3-small @ $0.02/M)",
        f"  estimated wall-clock      : ~{wall_clock_min:.0f} min @ 3 rps",
        "",
        "  rate limit                : 3 rps, hourly budget 1000 pages "
        f"(instance=workspace {workspace})",
        f"  redact policy             : kb/redactor.py default "
        f"(vocab=org-{workspace})",
        "",
        "  permission lock            : share-in snapshot @ discover start (C1)",
        f"                              ({_fmt_int(visible_pages)} pages visible to integration; "
        "mid-run 404 → skipped[share_revoked])",
        "  cursor format              : last_edited_time:page_id (D2, opaque to backbone)",
        "",
        "[notion-backfill] DRY RUN — no rows written. "
        "Re-run without --dry-run to ingest.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI dispatcher for notion subcommand
# ---------------------------------------------------------------------------


async def main_async_notion(
    argv: list[str],
    *,
    db: Any,
    redactor: Any,
    embedder: Any,
    vault: Any | None = None,
    monthly_ceiling: int = 20_000_000,
) -> int:
    """Async entry point for ``breadmind kb backfill notion``.

    Returns exit codes per spec §8:
      0  success
      1  generic error
      2  budget exceeded
      3  auth fail
    """
    from breadmind.kb.backfill.cli import build_parser, _monthly_remaining

    args = build_parser().parse_args(argv)
    if args.subcommand != "notion":
        return 1

    until = args.until or datetime.now(timezone.utc)

    # Monthly budget pre-check (dry-run still allowed even if ceiling exhausted)
    remaining = await _monthly_remaining(db, args.org, monthly_ceiling)

    job = NotionBackfillAdapter(
        org_id=args.org,
        source_filter={"workspace": args.workspace},
        since=args.since,
        until=until,
        dry_run=args.dry_run,
        token_budget=args.token_budget,
        vault=vault,
    )

    runner = BackfillRunner(db=db, redactor=redactor, embedder=embedder)

    try:
        report = await runner.run(job)
    except PermissionError as exc:
        print(f"[notion-backfill] auth failed: {exc}")
        return 3
    except Exception as exc:
        print(f"[notion-backfill] error: {exc}")
        return 1

    if args.dry_run:
        ctx = {
            "workspace": args.workspace,
            "since": args.since,
            "until": until if args.until else None,
            "token_budget": args.token_budget,
            "monthly_remaining": remaining,
            "monthly_ceiling": monthly_ceiling,
            "inline_db_count": 0,
            "rows_queued": 0,
            "visible_pages": report.progress.discovered,
        }
        print(format_notion_dry_run(report, ctx))

        # Budget exceeded check
        est = report.estimated_tokens
        monthly_used_after = monthly_ceiling - remaining + est
        if est > args.token_budget or monthly_used_after > monthly_ceiling:
            return 2
        return 0

    print(
        f"indexed={report.indexed_count} "
        f"errors={report.errors} cursor={report.cursor}"
    )
    return 0
