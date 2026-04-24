"""Rich TUI renderer for ``breadmind jobs watch``.

This module holds the rich-based TUI half of ``jobs watch``. It is imported
lazily from :mod:`breadmind.cli.jobs_watch` so plain-mode runs do not require
``rich`` to be installed.

Architecture
------------
:class:`JobsWatchState` is a pure in-memory model that accumulates
broadcast events (``coding_job_*``, ``phase_*``, ``coding_phase_log``) into
a coherent snapshot, then renders itself as a :class:`rich.panel.Panel`.
Keeping the state object separate from the I/O loop (:func:`cmd_watch_tui`)
lets us unit-test the renderer without a WebSocket or a live terminal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterable


@dataclass
class JobsWatchState:
    """Accumulates broadcast events for a single job and renders the TUI panel."""

    job_id: str
    project: str = ""
    agent: str = ""
    status: str = "pending"
    total_phases: int = 0
    completed_phases: int = 0
    progress_pct: int = 0
    phases: list[dict] = field(default_factory=list)
    logs_by_phase: dict[int, list[str]] = field(default_factory=dict)
    selected_phase: int = 1

    def apply(self, ev: dict) -> None:
        """Mutate state from a single broadcast event.

        Events whose ``data.job_id`` does not match are silently dropped so
        callers can feed a shared event stream without pre-filtering.
        """
        data = ev.get("data", {}) or {}
        if data.get("job_id") != self.job_id:
            return
        t = ev.get("type", "")
        if t.startswith("coding_job_") or t in ("phase_started", "phase_completed", "phase_failed"):
            self.project = data.get("project", self.project)
            self.agent = data.get("agent", self.agent)
            self.status = data.get("status", self.status)
            self.total_phases = data.get("total_phases", self.total_phases)
            self.completed_phases = data.get("completed_phases", self.completed_phases)
            self.progress_pct = data.get("progress_pct", self.progress_pct)
            if data.get("phases"):
                self.phases = data["phases"]
            if data.get("current_phase"):
                self.selected_phase = data["current_phase"]
        elif t == "coding_phase_log":
            step = int(data.get("step", 0))
            text = data.get("text", "")
            self.logs_by_phase.setdefault(step, []).append(text)

    def render_panel(self):
        """Build a :class:`rich.panel.Panel` snapshot of the current state."""
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        remaining = max(self.total_phases - self.completed_phases, 0)
        dots = "●" * self.completed_phases + "○" * remaining
        header = Text(
            f"Job {self.job_id} — {self.project} ({self.agent})  "
            f"{dots}  {self.completed_phases}/{self.total_phases} "
            f"({self.progress_pct}%)"
        )
        tbl = Table.grid(padding=(0, 1))
        status_icons = {
            "completed": "✔",
            "running": "▶",
            "pending": "□",
            "failed": "✗",
        }
        for p in self.phases:
            icon = status_icons.get(p.get("status", ""), "?")
            tbl.add_row(
                f"  {icon}",
                f"step {p['step']:>2}",
                p.get("title", ""),
                f"{p.get('duration_seconds', 0):.1f}s",
            )
        log_lines = self.logs_by_phase.get(self.selected_phase, [])[-20:]
        log_text = Text("\n".join(log_lines) or "(no logs yet)")
        return Panel(
            Group(header, tbl, Text("\n─ log ─", style="dim"), log_text),
            title="watch (press Ctrl+C to exit)",
        )


async def cmd_watch_tui(
    job_id: str,
    *,
    event_source: AsyncIterable[dict[str, Any]],
    phase: int | None,
) -> int:
    """Render a live rich TUI until the job reaches a terminal state.

    ``event_source`` is any async iterable of event dicts — in production
    it's the server WebSocket; in tests it's a fake async generator.
    """
    from rich.console import Console
    from rich.live import Live

    st = JobsWatchState(job_id=job_id, selected_phase=phase or 1)
    console = Console()
    with Live(st.render_panel(), console=console, refresh_per_second=4) as live:
        async for ev in event_source:
            st.apply(ev)
            live.update(st.render_panel())
            if ev.get("type") in ("coding_job_completed", "coding_job_cancelled"):
                return 0
            if ev.get("type") == "coding_job_failed":
                return 1
    return 0
