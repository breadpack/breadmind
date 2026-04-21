"""Seed the pilot Postgres with 2 projects, 10 users, 5 channels, 50 KB items.

Usage:
    python scripts/seed_pilot_data.py --dsn postgresql://breadmind@localhost/breadmind

Idempotent: re-running rewrites the same rows (matched by name).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

import asyncpg

CATEGORIES = ["howto", "decision", "bug_fix", "onboarding", "sensitive_blocked"]
PROJECTS = [("pilot-alpha", "T-PILOT-ALPHA"), ("pilot-beta", "T-PILOT-BETA")]
USERS = [f"U-PILOT-{i:02d}" for i in range(10)]
CHANNELS = [
    ("C-ALPHA-GENERAL", "pilot-alpha", "project_public"),
    ("C-ALPHA-HR",      "pilot-alpha", "channel_members_only"),
    ("C-BETA-GENERAL",  "pilot-beta",  "project_public"),
    ("C-BETA-DEV",      "pilot-beta",  "channel_members_only"),
    ("C-BETA-ONBOARD",  "pilot-beta",  "project_public"),
]

SLACK_EVENT_FIXTURES = [
    {"type": "app_mention", "user": USERS[0], "channel": "C-ALPHA-GENERAL",
     "text": "<@BREADMIND> 결제 모듈 메모리 누수 이슈 어떻게 해결했더라?",
     "ts": "1700000000.000001"},
    {"type": "team_join", "user": "U-NEW-JOINER",
     "team": "T-PILOT-ALPHA",
     "event_ts": "1700000123.000001"},
]

CONFLUENCE_PAGE_FIXTURES = [
    {"id": "CONF-1", "title": "Payment memory leak postmortem",
     "space": "ENG", "body": "We patched the leak in CL 12345 by ..."},
    {"id": "CONF-2", "title": "Onboarding: dev environment",
     "space": "ONBOARD", "body": "Install Python 3.12, run pip install -e ..."},
]


async def _upsert_project(c: asyncpg.Connection, name: str, team: str) -> uuid.UUID:
    row = await c.fetchrow(
        "INSERT INTO org_projects (name, slack_team_id) VALUES ($1,$2) "
        "ON CONFLICT (name) DO UPDATE SET slack_team_id = EXCLUDED.slack_team_id "
        "RETURNING id",
        name, team,
    )
    return row["id"]


async def _seed_members(c: asyncpg.Connection, proj_id: uuid.UUID) -> None:
    for idx, uid in enumerate(USERS):
        role = "lead" if idx == 0 else "member"
        await c.execute(
            "INSERT INTO org_project_members (project_id,user_id,role) "
            "VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
            proj_id, uid, role,
        )


async def _seed_channels(c: asyncpg.Connection, projects: dict[str, uuid.UUID]) -> None:
    for ch_id, proj_name, vis in CHANNELS:
        await c.execute(
            "INSERT INTO org_channel_map (channel_id,project_id,visibility) "
            "VALUES ($1,$2,$3) "
            "ON CONFLICT (channel_id) DO UPDATE SET visibility=EXCLUDED.visibility",
            ch_id, projects[proj_name], vis,
        )


async def _seed_knowledge(c: asyncpg.Connection, projects: dict[str, uuid.UUID]) -> None:
    for proj in projects.values():
        for cat in CATEGORIES:
            for i in range(10):
                await c.execute(
                    "INSERT INTO org_knowledge "
                    "(project_id,title,body,category,source_channel,tags,promoted_from) "
                    "VALUES ($1,$2,$3,$4,$5,$6,'personal_kb') "
                    "ON CONFLICT DO NOTHING",
                    proj, f"{cat}-sample-{i}",
                    f"Seed body for {cat} #{i}. Lorem ipsum dolor sit amet.",
                    cat, None, [cat, "seed"],
                )


async def _write_fixtures_to_disk(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "slack_events.json").write_text(
        json.dumps(SLACK_EVENT_FIXTURES, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "confluence_pages.json").write_text(
        json.dumps(CONFLUENCE_PAGE_FIXTURES, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--fixtures-dir", default="tests/e2e/fixtures/data")
    args = ap.parse_args()

    conn = await asyncpg.connect(dsn=args.dsn)
    try:
        projects: dict[str, uuid.UUID] = {}
        for name, team in PROJECTS:
            projects[name] = await _upsert_project(conn, name, team)
        for proj in projects.values():
            await _seed_members(conn, proj)
        await _seed_channels(conn, projects)
        await _seed_knowledge(conn, projects)
    finally:
        await conn.close()

    await _write_fixtures_to_disk(Path(args.fixtures_dir))
    print("seed: done")


if __name__ == "__main__":
    asyncio.run(main())
