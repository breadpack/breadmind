"""PersonalContextProvider — injects upcoming events and pending tasks into LLM context."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from breadmind.memory.context_builder import ContextProvider

if TYPE_CHECKING:
    from breadmind.personal.adapters.base import AdapterRegistry


class PersonalContextProvider(ContextProvider):
    def __init__(self, adapter_registry: AdapterRegistry, default_user_id: str = "default") -> None:
        self._registry = adapter_registry
        self._default_user_id = default_user_id

    async def get_context(self, session_id: str, message: str, intent: Any) -> list:
        from breadmind.core.intent import IntentCategory

        category = getattr(intent, "category", None)
        if category not in (IntentCategory.SCHEDULE, IntentCategory.TASK):
            return []

        now = datetime.now(timezone.utc)
        context_parts: list[str] = []
        user_id = self._default_user_id
        suggestions: list[str] = []

        # Upcoming events (next 48 hours) — use cache for speed
        from breadmind.personal.cache import get_cache
        cache = get_cache()

        events: list = []
        cached_events = await cache.get("event:upcoming:default")
        if cached_events is not None:
            events = cached_events
        else:
            try:
                event_adapter = self._registry.get_adapter("event", "builtin")
                events = await event_adapter.list_items(
                    filters={"user_id": user_id, "start_after": now, "start_before": now + timedelta(hours=48)},
                    limit=10)
                await cache.set("event:upcoming:default", events, ttl=120)
            except KeyError:
                pass
        if events:
            event_lines = [f"  - {e.title} ({e.start_at.strftime('%m/%d %H:%M')})" for e in events]
            context_parts.append("Upcoming events (48h):\n" + "\n".join(event_lines))

        # Check if external calendar is connected
        try:
            gcal = self._registry.get_adapter("event", "google_calendar")
            if not getattr(gcal, "_oauth", None):
                suggestions.append(
                    "Google Calendar이 연결되지 않았습니다. 연결하면 일정을 자동으로 관리할 수 있습니다."
                )
        except KeyError:
            pass

        # Pending tasks due soon (next 48 hours) — use cache for speed
        tasks: list = []
        cached_tasks = await cache.get("task:pending:default")
        if cached_tasks is not None:
            tasks = cached_tasks
        else:
            try:
                task_adapter = self._registry.get_adapter("task", "builtin")
                tasks = await task_adapter.list_items(
                    filters={"user_id": user_id, "status": "pending", "due_before": now + timedelta(hours=48)},
                    limit=10)
                await cache.set("task:pending:default", tasks, ttl=120)
            except KeyError:
                pass
        if tasks:
            task_lines = [
                f"  - {t.title} (due: {t.due_at.strftime('%m/%d %H:%M') if t.due_at else 'none'})"
                for t in tasks
            ]
            context_parts.append("Pending tasks (due within 48h):\n" + "\n".join(task_lines))

        # Check external task services
        external_task_connected = False
        for source in ["notion", "jira", "github"]:
            try:
                adapter = self._registry.get_adapter("task", source)
                if (
                    getattr(adapter, "_api_key", None)
                    or getattr(adapter, "_token", None)
                    or getattr(adapter, "_auth_header", None)
                ):
                    external_task_connected = True
                    break
            except KeyError:
                pass

        if not external_task_connected and category == IntentCategory.TASK:
            suggestions.append(
                "Notion, Jira, GitHub 등의 서비스를 연결하면 할 일을 통합 관리할 수 있습니다."
            )

        if suggestions:
            context_parts.append(
                "Service suggestions:\n" + "\n".join(f"  💡 {s}" for s in suggestions)
            )

        if not context_parts:
            return []

        from breadmind.llm.base import LLMMessage
        return [LLMMessage(
            role="system",
            content="## Personal Context\n" + "\n\n".join(context_parts),
        )]
