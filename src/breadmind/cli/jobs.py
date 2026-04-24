# src/breadmind/cli/jobs.py
"""`breadmind jobs` subcommand — list/show/cancel/logs/watch."""
from __future__ import annotations

import getpass
import json
import os
import sys


class JobsApiClient:
    """HTTP client used by CLI subcommands."""
    def __init__(self, base_url: str, api_key: str) -> None:
        import httpx
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=30.0,
            # API versioning middleware rewrites /api/... -> /api/v1/...
            # via 307; follow transparently so the CLI sees the real status.
            follow_redirects=True,
        )

    async def list_jobs(self, *, mine: bool, status: str | None, limit: int) -> list[dict]:
        params = {"limit": limit}
        if mine:
            params["mine"] = 1
        if status:
            params["status"] = status
        r = await self._http.get("/api/coding-jobs", params=params)
        r.raise_for_status()
        return r.json()

    async def get_job(self, job_id: str) -> dict | None:
        r = await self._http.get(f"/api/coding-jobs/{job_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def cancel_job(self, job_id: str) -> int:
        r = await self._http.post(f"/api/coding-jobs/{job_id}/cancel")
        return r.status_code

    async def list_logs(self, job_id: str, step: int, *, after: int | None, limit: int) -> dict:
        params = {"limit": limit}
        if after is not None:
            params["after_line_no"] = after
        r = await self._http.get(f"/api/coding-jobs/{job_id}/phases/{step}/logs", params=params)
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        await self._http.aclose()


def build_client_from_env(args) -> JobsApiClient:
    base = os.environ.get("BREADMIND_URL", "http://localhost:8080")
    key = getattr(args, "api_key", None) or os.environ.get("BREADMIND_API_KEY", "")
    return JobsApiClient(base_url=base, api_key=key)


def resolve_user(args) -> str:
    return getattr(args, "as_user", None) or getpass.getuser()


async def cmd_list(client, *, mine: bool, status: str | None, limit: int, fmt: str) -> int:
    jobs = await client.list_jobs(mine=mine, status=status, limit=limit)
    if fmt == "json":
        print(json.dumps(jobs, indent=2, default=str))
    else:
        print(f"{'ID':<12} {'STATUS':<10} {'PROJECT':<12} {'USER':<10} {'PROGRESS':<10} PROMPT")
        for j in jobs:
            pct = j.get("progress_pct", 0)
            print(
                f"{j['job_id'][:12]:<12} {j['status']:<10} {j.get('project','')[:12]:<12} "
                f"{j.get('user','')[:10]:<10} {pct}%{'':<7} {j.get('prompt','')[:60]}"
            )
    return 0


async def cmd_show(client, job_id: str, *, fmt: str) -> int:
    job = await client.get_job(job_id)
    if not job:
        print(f"job {job_id} not found (or not accessible)")
        return 2
    if fmt == "json":
        print(json.dumps(job, indent=2, default=str))
    else:
        print(f"Job {job['job_id']} — {job.get('project')} ({job.get('agent')})")
        print(f"  user: {job.get('user','')}  status: {job['status']}  "
              f"progress: {job.get('completed_phases',0)}/{job.get('total_phases',0)} "
              f"({job.get('progress_pct',0)}%)")
        for p in job.get("phases", []):
            icon = {"completed": "✔", "running": "▶", "pending": "□", "failed": "✗"}.get(p["status"], "?")
            print(f"  {icon} step {p['step']:>2}  {p['title']:<30}  "
                  f"{p.get('duration_seconds',0):.1f}s  files={len(p.get('files_changed',[]))}")
    return 0


async def cmd_cancel(client, job_id: str) -> int:
    status = await client.cancel_job(job_id)
    if status == 200:
        print(f"cancelled {job_id}")
        return 0
    if status == 403:
        print(f"forbidden — not owner of {job_id}", file=sys.stderr)
        return 3
    if status == 404:
        print(f"job {job_id} not found", file=sys.stderr)
        return 2
    print(f"cancel failed (HTTP {status})", file=sys.stderr)
    return 1


async def cmd_logs(
    client, job_id: str, *, phase: int, follow: bool, lines: int, plain: bool,
) -> int:
    page = await client.list_logs(job_id, phase, after=None, limit=lines)
    for item in page.get("items", []):
        print(f"[{item['ts']}] {item['text']}")
    if not follow:
        return 0
    # Follow mode: poll at 1s intervals via cursor
    import asyncio
    after = page.get("next_after_line_no")
    while True:
        await asyncio.sleep(1.0)
        page = await client.list_logs(job_id, phase, after=after, limit=500)
        for item in page.get("items", []):
            print(f"[{item['ts']}] {item['text']}")
        if page.get("next_after_line_no"):
            after = page["next_after_line_no"]
