"""E2E: long-running coding-job monitoring — REST + DB + CLI.

Exercises the full stack:

1. ``JobTracker`` singleton drives a two-phase job through its lifecycle,
   write-through persisting to Postgres (via testcontainers).
2. REST endpoints ``GET /api/coding-jobs/{id}`` and
   ``GET /api/coding-jobs/{id}/phases/{step}/logs`` are hit over real HTTP
   against a running uvicorn server.
3. The ``breadmind jobs show`` / ``breadmind jobs cancel`` CLI
   subcommands are spawned as subprocesses so the HTTP client path in
   ``src/breadmind/cli/jobs.py`` is exercised end-to-end.

Requires a running Docker daemon for the testcontainers-managed
Postgres. The module-level ``_docker_available`` check emits a
``pytest.skip`` with a clear message if Docker is unreachable, so a
laptop without Docker running still collects cleanly instead of tripping
the testcontainers import at fixture setup time.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest


def _docker_available() -> bool:
    """Return True if the local Docker daemon is reachable."""
    try:
        import docker  # type: ignore
    except Exception:
        return False
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _docker_available(),
        reason="Docker daemon not reachable — testcontainers cannot start Postgres",
    ),
]


async def test_full_monitoring_flow(postgres_container, breadmind_server):
    """End-to-end round-trip of a completed two-phase coding job.

    Drives a job through ``JobTracker``, then verifies:
    * the REST detail endpoint reflects status=completed / total_phases=2
    * the per-phase logs endpoint returns the lines we appended
    * the ``breadmind jobs show --format json`` CLI round-trips job_id
    * the ``breadmind jobs cancel`` CLI returns a non-zero exit on a
      job that is already terminal (expected failure path)
    """
    import httpx

    from breadmind.coding.job_tracker import JobTracker

    tracker = JobTracker.get_instance()
    tracker.create_job(
        "e2e-1", "p", "claude", "test prompt",
        user="tester", channel="",
    )
    tracker.set_phases("e2e-1", [
        {"step": 1, "title": "one"},
        {"step": 2, "title": "two"},
    ])
    tracker.start_phase("e2e-1", 1)
    await tracker.append_log("e2e-1", 1, "hello from phase 1")
    tracker.complete_phase("e2e-1", 1, success=True, output="ok")
    tracker.start_phase("e2e-1", 2)
    await tracker.append_log("e2e-1", 2, "hello from phase 2")
    tracker.complete_phase("e2e-1", 2, success=True, output="ok")
    tracker.complete_job("e2e-1", success=True, session_id="sess")

    # Drain any pending DB write-through and log-buffer flushes so the
    # subsequent REST reads see the final state.
    if tracker._db_queue is not None:
        await tracker._db_queue.join()
    if tracker._log_buffer is not None:
        # Signal log-buffer worker to drain; small sleep below gives it
        # time to complete (force_flush is fire-and-forget post-Task 10).
        await tracker._log_buffer.force_flush("e2e-1", 1)
        await tracker._log_buffer.force_flush("e2e-1", 2)
        await asyncio.sleep(0.1)

    base = breadmind_server["url"]
    api_key = breadmind_server["api_key"]

    # ── REST check ─────────────────────────────────────────────────────
    # ``follow_redirects=True`` because ``setup_versioning`` rewrites
    # un-versioned ``/api/...`` to ``/api/v1/...`` via a 307 redirect.
    async with httpx.AsyncClient(
        base_url=base,
        headers={"X-API-Key": api_key},
        timeout=10.0,
        follow_redirects=True,
    ) as c:
        r = await c.get("/api/coding-jobs/e2e-1")
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["job_id"] == "e2e-1"
        assert job["status"] == "completed"
        assert job["total_phases"] == 2

        r = await c.get("/api/coding-jobs/e2e-1/phases/1/logs")
        assert r.status_code == 200, r.text
        logs = r.json()
        texts = [item["text"] for item in logs["items"]]
        assert "hello from phase 1" in texts

    # ── CLI check: jobs show --format json ─────────────────────────────
    env = {
        "BREADMIND_URL": base,
        "BREADMIND_API_KEY": api_key,
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        # Preserve SystemRoot/USERPROFILE so subprocess Python starts on
        # Windows (otherwise socket lookups fail under cmd).
        **{
            k: os.environ[k]
            for k in ("SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP")
            if k in os.environ
        },
    }

    proc = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "breadmind", "jobs", "show", "e2e-1",
         "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"jobs show failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    data = json.loads(proc.stdout)
    assert data["job_id"] == "e2e-1"
    assert data["status"] == "completed"

    # ── CLI cancel on terminal job — expected non-zero ─────────────────
    # ``cmd_cancel`` maps HTTP 400 ("already finished") to exit 1 and HTTP
    # 404 to exit 2. Either is an acceptable "you can't cancel this" signal.
    proc_c = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "breadmind", "jobs", "cancel", "e2e-1"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc_c.returncode in (1, 2), (
        f"expected non-zero exit on already-completed job, "
        f"got rc={proc_c.returncode} stdout={proc_c.stdout!r} "
        f"stderr={proc_c.stderr!r}"
    )
