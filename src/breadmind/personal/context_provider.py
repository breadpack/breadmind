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

        try:
            event_adapter = self._registry.get_adapter("event", "builtin")
            events = await event_adapter.list_items(
                filters={"user_id": user_id, "start_after": now, "start_before": now + timedelta(hours=48)},
                limit=10)
            if events:
                event_lines = [f"  - {e.title} ({e.start_at.strftime('%m/%d %H:%M')})" for e in events]
                context_parts.append("Upcoming events (48h):\n" + "\n".join(event_lines))
        except KeyError:
            pass

        try:
            task_adapter = self._registry.get_adapter("task", "builtin")
            tasks = await task_adapter.list_items(
                filters={"user_id": user_id, "status": "pending", "due_before": now + timedelta(hours=48)},
                limit=10)
            if tasks:
                task_lines = [f"  - {t.title} (due: {t.due_at.strftime('%m/%d %H:%M') if t.due_at else 'none'})" for t in tasks]
                context_parts.append("Pending tasks (due within 48h):\n" + "\n".join(task_lines))
        except KeyError:
            pass

        if not context_parts:
            return []

        from breadmind.llm.base import LLMMessage
        return [LLMMessage(role="system", content="## Personal Context\n" + "\n\n".join(context_parts))]
