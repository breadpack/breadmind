# src/breadmind/cli/jobs_watch.py
"""`breadmind jobs watch` — plain tail + TTY switch.

This module implements the plain-text streaming half of the ``jobs watch``
CLI. The TUI variant lives in a sibling module (Task 21) and is imported
lazily inside :func:`cmd_watch` so importing this file never requires
`rich`/`textual` to be installed.

Event source abstraction
------------------------
:func:`cmd_watch_plain` accepts any async iterable of event dicts. In
production we feed it :func:`_ws_event_source` which connects to the
server's WebSocket broadcast channel. In unit tests we feed it a fake
async generator — see ``tests/cli/test_jobs_commands.py``.
"""
from __future__ import annotations

import json
import sys
from typing import Any, AsyncIterable


def _format_event(evt: dict[str, Any]) -> str | None:
    """Render a single event dict as one plain line, or ``None`` to skip.

    Unknown event types fall back to a ``type  json``-dump form so the
    operator can at least see raw payloads while we iterate on the schema.
    Events whose ``data.job_id`` does not match the job we're watching are
    filtered out upstream by :func:`cmd_watch_plain`.
    """
    t = evt.get("type") or ""
    d = evt.get("data") or {}
    if t == "coding_phase_log":
        return f"[{d.get('ts','')}] step={d.get('step','?')} {d.get('text','')}"
    if t in (
        "coding_job_running",
        "coding_job_created",
        "coding_job_started",
        "coding_job_completed",
        "coding_job_failed",
        "coding_job_cancelled",
        "phase_started",
        "phase_completed",
        "phase_failed",
    ):
        parts = [t]
        for k in ("current_phase", "total_phases", "status", "reason"):
            if k in d:
                parts.append(f"{k}={d[k]}")
        return " ".join(parts)
    return f"{t}  {json.dumps(d, default=str)}"


async def cmd_watch_plain(
    job_id: str,
    *,
    event_source: AsyncIterable[dict[str, Any]],
) -> int:
    """Tail events for *job_id* as plain text; exits on terminal event.

    Returns 0 on ``completed``/``cancelled`` (expected terminals), 1 on
    ``failed``. The caller is responsible for opening/closing the event
    source — we only iterate.
    """
    async for evt in event_source:
        # Filter by job_id when the event carries one; pass through
        # envelope-only events (rare, but tolerated).
        data = evt.get("data") or {}
        if data.get("job_id") and data["job_id"] != job_id:
            continue
        line = _format_event(evt)
        if line is not None:
            print(line, flush=True)
        t = evt.get("type") or ""
        if t in ("coding_job_completed", "coding_job_cancelled"):
            return 0
        if t == "coding_job_failed":
            return 1
    return 0


async def _ws_event_source(
    base_url: str,
    api_key: str,
    token: str | None = None,
) -> AsyncIterable[dict[str, Any]]:
    """Connect to the server WebSocket broadcast and yield decoded events.

    The import of :mod:`websockets` is intentionally lazy: the CLI should
    remain importable on systems that only installed the core extras.
    """
    import websockets  # lazy: optional dep

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    if not ws_url.endswith("/ws"):
        ws_url = ws_url.rstrip("/") + "/ws"
    headers = {"X-API-Key": api_key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with websockets.connect(ws_url, extra_headers=headers) as ws:
        async for raw in ws:
            try:
                yield json.loads(raw)
            except Exception:
                continue


async def cmd_watch(
    job_id: str,
    *,
    plain: bool,
    phase: int | None,
    base_url: str,
    api_key: str,
    token: str | None,
) -> int:
    """Dispatch to plain tail or TUI based on flags / TTY detection.

    ``plain=True`` or a non-TTY stdout forces plain-text output. When
    attached to a TTY and ``plain`` is false, we import and hand off to
    :func:`cmd_watch_tui` (Task 21). The TUI import is intentionally
    deferred so plain-mode runs don't require ``rich``/``textual``.
    """
    source = _ws_event_source(base_url, api_key, token)
    if plain or not sys.stdout.isatty():
        return await cmd_watch_plain(job_id, event_source=source)
    from breadmind.cli.jobs_watch_tui import cmd_watch_tui  # lazy
    return await cmd_watch_tui(
        job_id,
        phase=phase,
        event_source=source,
    )
