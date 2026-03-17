"""PersonalScheduler — proactive reminders and deadline warnings."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from breadmind.personal.adapters.base import AdapterRegistry

logger = logging.getLogger(__name__)


class PersonalScheduler:
    def __init__(self, adapter_registry: AdapterRegistry, messenger_router: Any,
                 check_interval: int = 60, default_user_id: str = "default") -> None:
        self._registry = adapter_registry
        self._router = messenger_router
        self._check_interval = check_interval
        self._default_user_id = default_user_id
        self._notified: set[str] = set()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("PersonalScheduler started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self._check_reminders()
                await self._check_deadlines()
                await self._check_overdue()
            except Exception:
                logger.exception("PersonalScheduler check failed")
            await asyncio.sleep(self._check_interval)

    async def _check_reminders(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            adapter = self._registry.get_adapter("event", "builtin")
        except KeyError:
            return
        events = await adapter.list_items(
            filters={"user_id": self._default_user_id, "start_after": now,
                     "start_before": now + timedelta(hours=2)}, limit=20)
        for event in events:
            for minutes in event.reminder_minutes:
                diff_minutes = (event.start_at - now).total_seconds() / 60
                notify_key = f"reminder:{event.id}:{minutes}"
                if 0 <= diff_minutes <= minutes and notify_key not in self._notified:
                    msg = f"\U0001f4c5 {int(diff_minutes)}\ubd84 \ud6c4: {event.title}"
                    if event.location:
                        msg += f" @ {event.location}"
                    await self._router.broadcast_notification(msg)
                    self._notified.add(notify_key)

    async def _check_deadlines(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            adapter = self._registry.get_adapter("task", "builtin")
        except KeyError:
            return
        tasks = await adapter.list_items(
            filters={"user_id": self._default_user_id, "status": "pending",
                     "due_before": now + timedelta(hours=24)}, limit=20)
        for task in tasks:
            notify_key = f"deadline:{task.id}"
            if notify_key not in self._notified:
                hours_left = (task.due_at - now).total_seconds() / 3600 if task.due_at else 0
                msg = f"\u26a0\ufe0f \ub9c8\uac10 \uc784\ubc15: {task.title} ({int(hours_left)}\uc2dc\uac04 \ub0a8\uc74c)"
                await self._router.broadcast_notification(msg)
                self._notified.add(notify_key)

    async def generate_daily_summary(self) -> str:
        """Generate a daily summary of tasks and events."""
        now = datetime.now(timezone.utc)
        lines = ["\U0001f4cb \uc624\ub298\uc758 \uc694\uc57d:"]

        # Today's events
        try:
            event_adapter = self._registry.get_adapter("event", "builtin")
            events = await event_adapter.list_items(
                filters={"user_id": self._default_user_id,
                         "start_after": now, "start_before": now + timedelta(hours=24)},
                limit=20)
            if events:
                lines.append("\n\U0001f4c5 \uc624\ub298\uc758 \uc77c\uc815:")
                for e in events:
                    lines.append(f"  \u2022 {e.title} ({e.start_at.strftime('%H:%M')}~{e.end_at.strftime('%H:%M')})")
        except KeyError:
            pass

        # Pending tasks
        try:
            task_adapter = self._registry.get_adapter("task", "builtin")
            tasks = await task_adapter.list_items(
                filters={"user_id": self._default_user_id, "status": "pending"},
                limit=20)
            if tasks:
                lines.append("\n\u2705 \ud560 \uc77c:")
                for t in tasks:
                    due_str = f" (\ub9c8\uac10: {t.due_at.strftime('%m/%d %H:%M')})" if t.due_at else ""
                    lines.append(f"  \u2022 {t.title}{due_str}")
        except KeyError:
            pass

        return "\n".join(lines)

    async def _check_overdue(self) -> None:
        """Check for tasks past their deadline."""
        now = datetime.now(timezone.utc)
        try:
            adapter = self._registry.get_adapter("task", "builtin")
        except KeyError:
            return

        # Get all pending tasks (we'll filter overdue ones in Python)
        tasks = await adapter.list_items(
            filters={"user_id": self._default_user_id, "status": "pending"},
            limit=50)

        for task in tasks:
            if task.due_at and task.due_at < now:
                notify_key = f"overdue:{task.id}"
                if notify_key not in self._notified:
                    hours_over = (now - task.due_at).total_seconds() / 3600
                    msg = f"\U0001f6a8 \uc9c0\uc5f0\ub428: {task.title} ({int(hours_over)}\uc2dc\uac04 \ucd08\uacfc)"
                    await self._router.broadcast_notification(msg)
                    self._notified.add(notify_key)

    def clear_notifications(self) -> None:
        self._notified.clear()
