"""Cross-domain query engine for personal assistant.

Enables queries that span multiple domains (e.g., "tasks due before next meeting").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from breadmind.personal.adapters.base import AdapterRegistry
from breadmind.personal.models import Task, Event


class CrossDomainQuery:
    """Executes queries spanning multiple domain entities."""

    def __init__(self, adapter_registry: AdapterRegistry) -> None:
        self._registry = adapter_registry

    async def tasks_before_next_event(self, user_id: str) -> dict:
        """Find pending tasks due before the next upcoming event."""
        now = datetime.now(timezone.utc)

        # Get next event
        try:
            event_adapter = self._registry.get_adapter("event", "builtin")
            events = await event_adapter.list_items(
                filters={"user_id": user_id, "start_after": now},
                limit=1,
            )
        except KeyError:
            events = []

        if not events:
            return {
                "next_event": None,
                "tasks_due_before": [],
                "message": "예정된 일정이 없습니다.",
            }

        next_event = events[0]

        # Get tasks due before that event
        try:
            task_adapter = self._registry.get_adapter("task", "builtin")
            tasks = await task_adapter.list_items(
                filters={
                    "user_id": user_id,
                    "status": "pending",
                    "due_before": next_event.start_at,
                },
                limit=20,
            )
        except KeyError:
            tasks = []

        return {
            "next_event": next_event,
            "tasks_due_before": tasks,
            "message": self._format_tasks_before_event(next_event, tasks),
        }

    async def daily_agenda(
        self, user_id: str, date: datetime | None = None
    ) -> dict:
        """Get combined agenda for a specific day (events + due tasks)."""
        if date is None:
            date = datetime.now(timezone.utc)

        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # Get events for the day
        try:
            event_adapter = self._registry.get_adapter("event", "builtin")
            events = await event_adapter.list_items(
                filters={
                    "user_id": user_id,
                    "start_after": day_start,
                    "start_before": day_end,
                },
                limit=50,
            )
        except KeyError:
            events = []

        # Get tasks due that day
        try:
            task_adapter = self._registry.get_adapter("task", "builtin")
            tasks = await task_adapter.list_items(
                filters={
                    "user_id": user_id,
                    "status": "pending",
                    "due_before": day_end,
                },
                limit=50,
            )
        except KeyError:
            tasks = []

        return {
            "date": day_start,
            "events": events,
            "tasks": tasks,
            "message": self._format_daily_agenda(day_start, events, tasks),
        }

    async def find_free_slots(
        self,
        user_id: str,
        duration_minutes: int = 60,
        days_ahead: int = 3,
    ) -> list[dict]:
        """Find free time slots between events."""
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days_ahead)

        try:
            event_adapter = self._registry.get_adapter("event", "builtin")
            events = await event_adapter.list_items(
                filters={
                    "user_id": user_id,
                    "start_after": now,
                    "start_before": end,
                },
                limit=100,
            )
        except KeyError:
            return [
                {
                    "start": now,
                    "end": end,
                    "duration_minutes": int(
                        (end - now).total_seconds() / 60
                    ),
                }
            ]

        # Sort events by start time
        events.sort(key=lambda e: e.start_at)

        free_slots: list[dict] = []
        current = now

        for event in events:
            gap = (event.start_at - current).total_seconds() / 60
            if gap >= duration_minutes:
                free_slots.append(
                    {
                        "start": current,
                        "end": event.start_at,
                        "duration_minutes": int(gap),
                    }
                )
            current = max(current, event.end_at)

        # Check remaining time after last event
        if current < end:
            gap = (end - current).total_seconds() / 60
            if gap >= duration_minutes:
                free_slots.append(
                    {
                        "start": current,
                        "end": end,
                        "duration_minutes": int(gap),
                    }
                )

        return free_slots

    def _format_tasks_before_event(
        self, event: Event, tasks: list[Task]
    ) -> str:
        lines = [
            f"다음 일정: {event.title}"
            f" ({event.start_at.strftime('%m/%d %H:%M')})"
        ]
        if tasks:
            lines.append(
                f"\n이전에 완료해야 할 할 일 ({len(tasks)}개):"
            )
            for t in tasks:
                due_str = (
                    f" (마감: {t.due_at.strftime('%m/%d %H:%M')})"
                    if t.due_at
                    else ""
                )
                lines.append(f"  - {t.title}{due_str}")
        else:
            lines.append(
                "\n이전에 완료해야 할 할 일이 없습니다."
            )
        return "\n".join(lines)

    def _format_daily_agenda(
        self,
        date: datetime,
        events: list[Event],
        tasks: list[Task],
    ) -> str:
        lines = [f"{date.strftime('%Y-%m-%d')} 일정:"]
        if events:
            lines.append("\n일정:")
            for e in events:
                lines.append(
                    f"  - {e.start_at.strftime('%H:%M')}"
                    f"~{e.end_at.strftime('%H:%M')} {e.title}"
                )
        if tasks:
            lines.append(f"\n마감 할 일 ({len(tasks)}개):")
            for t in tasks:
                due_str = (
                    f" ({t.due_at.strftime('%H:%M')})" if t.due_at else ""
                )
                lines.append(f"  - {t.title}{due_str}")
        if not events and not tasks:
            lines.append("\n일정과 할 일이 없습니다.")
        return "\n".join(lines)
