"""Personal assistant builtin plugin.

Provides 15 tools for tasks, calendar events, reminders, contacts,
files, messages, and service connections.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from breadmind.personal.models import Contact, Event, File, Task, normalize_recurrence
from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse an ISO 8601 datetime string to a timezone-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    value = value.strip()
    # Handle Z suffix
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class PersonalPlugin(BaseToolPlugin):
    name = "personal"
    version = "0.1.0"

    def __init__(self) -> None:
        self._tools: list = []

    async def setup(self, container: Any) -> None:
        self._registry = container.get("adapter_registry")
        self._user_id = "default"
        self._build_tools()

    def _build_tools(self) -> None:
        registry = self._registry
        user_id = self._user_id

        # ---- Task tools ----

        @tool(description="할 일을 생성합니다. title 필수, description/due_at/priority/tags 선택.")
        async def task_create(
            title: str,
            description: str = None,
            due_at: str = None,
            priority: str = "medium",
            tags: str = None,
        ) -> str:
            adapter = registry.get_adapter("task", "builtin")
            tag_list = [t.strip() for t in tags.split(",")] if tags else []
            task = Task(
                id=str(uuid.uuid4()),
                title=title,
                description=description,
                due_at=_parse_datetime(due_at),
                priority=priority,
                tags=tag_list,
                user_id=user_id,
            )
            task_id = await adapter.create_item(task)
            return f"할 일 생성 완료: '{title}' (ID: {task_id})"

        @tool(description="할 일 목록을 조회합니다. status/priority/due_before/tags 필터 선택.")
        async def task_list(
            status: str = None,
            priority: str = None,
            due_before: str = None,
            tags: str = None,
        ) -> str:
            adapter = registry.get_adapter("task", "builtin")
            filters: dict = {"user_id": user_id}
            if status:
                filters["status"] = status
            if priority:
                filters["priority"] = priority
            if due_before:
                filters["due_before"] = _parse_datetime(due_before)
            if tags:
                filters["tags"] = [t.strip() for t in tags.split(",")]
            items = await adapter.list_items(filters=filters)
            if not items:
                return "할 일이 없습니다."
            lines = []
            for i, item in enumerate(items, 1):
                title = getattr(item, "title", str(item))
                status_val = getattr(item, "status", "")
                lines.append(f"{i}. {title} [{status_val}]")
            return "\n".join(lines)

        @tool(description="할 일을 업데이트합니다. task_id 필수, status/title/due_at/priority 선택.")
        async def task_update(
            task_id: str,
            status: str = None,
            title: str = None,
            due_at: str = None,
            priority: str = None,
        ) -> str:
            adapter = registry.get_adapter("task", "builtin")
            changes: dict = {}
            if status:
                changes["status"] = status
            if title:
                changes["title"] = title
            if due_at:
                changes["due_at"] = _parse_datetime(due_at)
            if priority:
                changes["priority"] = priority
            await adapter.update_item(task_id, changes)
            return f"할 일 업데이트 완료 (ID: {task_id})"

        @tool(description="할 일을 삭제합니다. task_id 필수.")
        async def task_delete(task_id: str) -> str:
            adapter = registry.get_adapter("task", "builtin")
            await adapter.delete_item(task_id)
            return f"할 일 삭제 완료 (ID: {task_id})"

        # ---- Event tools ----

        @tool(description="캘린더 일정을 생성합니다. title/start_at 필수.")
        async def event_create(
            title: str,
            start_at: str,
            end_at: str = None,
            all_day: bool = False,
            location: str = None,
            attendees: str = None,
            reminder_minutes: str = None,
            recurrence: str = None,
        ) -> str:
            adapter = registry.get_adapter("event", "builtin")
            start_dt = _parse_datetime(start_at)
            if end_at:
                end_dt = _parse_datetime(end_at)
            else:
                end_dt = start_dt + timedelta(hours=1)

            attendee_list = (
                [a.strip() for a in attendees.split(",")] if attendees else []
            )
            reminder_list = (
                [int(m.strip()) for m in reminder_minutes.split(",")]
                if reminder_minutes
                else [15]
            )

            event = Event(
                id=str(uuid.uuid4()),
                title=title,
                start_at=start_dt,
                end_at=end_dt,
                all_day=all_day,
                location=location,
                attendees=attendee_list,
                reminder_minutes=reminder_list,
                recurrence=normalize_recurrence(recurrence),
                user_id=user_id,
            )
            event_id = await adapter.create_item(event)
            return f"일정 생성 완료: '{title}' (ID: {event_id})"

        @tool(description="캘린더 일정을 조회합니다. start_after/start_before 필터 선택.")
        async def event_list(
            start_after: str = None,
            start_before: str = None,
        ) -> str:
            adapter = registry.get_adapter("event", "builtin")
            filters: dict = {"user_id": user_id}
            if start_after:
                filters["start_after"] = _parse_datetime(start_after)
            if start_before:
                filters["start_before"] = _parse_datetime(start_before)
            items = await adapter.list_items(filters=filters)
            if not items:
                return "일정이 없습니다."
            lines = []
            for i, item in enumerate(items, 1):
                title = getattr(item, "title", str(item))
                start = getattr(item, "start_at", "")
                lines.append(f"{i}. {title} ({start})")
            return "\n".join(lines)

        @tool(description="캘린더 일정을 업데이트합니다. event_id 필수.")
        async def event_update(
            event_id: str,
            title: str = None,
            start_at: str = None,
            end_at: str = None,
            location: str = None,
        ) -> str:
            adapter = registry.get_adapter("event", "builtin")
            changes: dict = {}
            if title:
                changes["title"] = title
            if start_at:
                changes["start_at"] = _parse_datetime(start_at)
            if end_at:
                changes["end_at"] = _parse_datetime(end_at)
            if location:
                changes["location"] = location
            await adapter.update_item(event_id, changes)
            return f"일정 업데이트 완료 (ID: {event_id})"

        @tool(description="캘린더 일정을 삭제합니다. event_id 필수.")
        async def event_delete(event_id: str) -> str:
            adapter = registry.get_adapter("event", "builtin")
            await adapter.delete_item(event_id)
            return f"일정 삭제 완료 (ID: {event_id})"

        # ---- Reminder tool ----

        @tool(description="리마인더를 설정합니다. message/remind_at 필수, recurrence 선택.")
        async def reminder_set(
            message: str,
            remind_at: str,
            recurrence: str = None,
        ) -> str:
            adapter = registry.get_adapter("event", "builtin")
            remind_dt = _parse_datetime(remind_at)
            event = Event(
                id=str(uuid.uuid4()),
                title=f"[리마인더] {message}",
                start_at=remind_dt,
                end_at=remind_dt,
                reminder_minutes=[0],
                recurrence=normalize_recurrence(recurrence),
                user_id=user_id,
            )
            event_id = await adapter.create_item(event)
            return f"리마인더 설정 완료: '{message}' @ {remind_at} (ID: {event_id})"

        # ---- Contact tools ----

        @tool(description="연락처를 검색합니다. query 필수.")
        async def contact_search(query: str) -> str:
            try:
                adapter = registry.get_adapter("contact", "builtin")
            except KeyError:
                adapters = registry.list_adapters("contact")
                if not adapters:
                    return "연락처 어댑터가 설정되지 않았습니다."
                adapter = adapters[0]

            contacts = await adapter.list_items(
                filters={"user_id": user_id, "query": query}, limit=10,
            )
            if not contacts:
                return f"'{query}'에 대한 연락처를 찾을 수 없습니다."

            lines = ["연락처 검색 결과:"]
            for c in contacts:
                parts = [f"  - {c.name}"]
                if c.email:
                    parts.append(c.email)
                if c.phone:
                    parts.append(c.phone)
                if c.organization:
                    parts.append(c.organization)
                lines.append(" | ".join(parts))
            return "\n".join(lines)

        @tool(description="연락처를 추가합니다. name 필수, email/phone/organization 선택.")
        async def contact_create(
            name: str,
            email: str = None,
            phone: str = None,
            organization: str = None,
        ) -> str:
            try:
                adapter = registry.get_adapter("contact", "builtin")
            except KeyError:
                adapters = registry.list_adapters("contact")
                if not adapters:
                    return "연락처 어댑터가 설정되지 않았습니다."
                adapter = adapters[0]

            contact = Contact(
                id="", name=name, email=email, phone=phone,
                organization=organization, user_id=user_id,
            )
            contact_id = await adapter.create_item(contact)
            return f"연락처 추가 완료: {name} [ID: {contact_id}]"

        # ---- File tools ----

        @tool(description="파일을 검색합니다. query 필수, source 선택.")
        async def file_search(query: str, source: str = None) -> str:
            adapters = registry.list_adapters("file")
            if source:
                try:
                    adapters = [registry.get_adapter("file", source)]
                except KeyError:
                    return f"파일 어댑터 '{source}'를 찾을 수 없습니다."
            if not adapters:
                return "파일 어댑터가 설정되지 않았습니다."

            all_files: list[File] = []
            for adapter in adapters:
                files = await adapter.list_items(
                    filters={"user_id": user_id, "name_contains": query},
                    limit=10,
                )
                all_files.extend(files)

            if not all_files:
                return f"'{query}'에 대한 파일을 찾을 수 없습니다."

            lines = ["파일 검색 결과:"]
            for f in all_files:
                size_str = _format_size(f.size_bytes) if f.size_bytes else ""
                source_str = f" [{f.source}]" if f.source != "local" else ""
                lines.append(
                    f"  - {f.name} ({f.mime_type}"
                    f"{', ' + size_str if size_str else ''}){source_str}",
                )
            return "\n".join(lines)

        @tool(description="파일 목록을 조회합니다. source 선택.")
        async def file_list(source: str = None) -> str:
            return await file_search(query="", source=source)

        # ---- Message tools ----

        @tool(description="대화 기록을 검색합니다. query 필수, channel 선택.")
        async def message_search(query: str, channel: str = None) -> str:
            adapters = registry.list_adapters("message")
            if not adapters:
                return "메시지 어댑터가 설정되지 않았습니다."

            all_messages = []
            filters = {"user_id": user_id, "query": query}
            if channel:
                filters["channel"] = channel

            for adapter in adapters:
                messages = await adapter.list_items(filters=filters, limit=10)
                all_messages.extend(messages)

            if not all_messages:
                return f"'{query}'에 대한 대화 기록을 찾을 수 없습니다."

            lines = ["대화 기록 검색 결과:"]
            for m in all_messages[:10]:
                preview = (
                    m.content[:100] + "..." if len(m.content) > 100 else m.content
                )
                lines.append(f"  - [{m.sender}] {preview}")
            return "\n".join(lines)

        # ---- Service connection tool ----

        @tool(description="외부 서비스(Google, Notion, Jira 등)를 연결합니다. service 필수.")
        async def service_connect(service: str) -> str:
            service_map = {
                "google": {
                    "name": "Google",
                    "type": "oauth",
                    "scopes": "calendar,drive,contacts",
                },
                "google_calendar": {
                    "name": "Google Calendar",
                    "type": "oauth",
                    "scopes": "calendar",
                },
                "google_drive": {
                    "name": "Google Drive",
                    "type": "oauth",
                    "scopes": "drive",
                },
                "google_contacts": {
                    "name": "Google Contacts",
                    "type": "oauth",
                    "scopes": "contacts",
                },
                "microsoft": {
                    "name": "Microsoft",
                    "type": "oauth",
                    "scopes": "calendar,files",
                },
                "outlook": {
                    "name": "Outlook Calendar",
                    "type": "oauth",
                    "scopes": "calendar",
                },
                "onedrive": {
                    "name": "OneDrive",
                    "type": "oauth",
                    "scopes": "files",
                },
                "notion": {"name": "Notion", "type": "api_key"},
                "jira": {"name": "Jira", "type": "api_token"},
                "github": {"name": "GitHub", "type": "token"},
            }

            # Normalize input
            key = (
                service.lower()
                .replace(" ", "_")
                .replace("캘린더", "calendar")
                .replace("구글", "google")
                .replace("마이크로소프트", "microsoft")
            )

            # Try exact match first, then partial match
            info = service_map.get(key)
            if not info:
                for k, v in service_map.items():
                    if key in k or k in key:
                        info = v
                        key = k
                        break

            if not info:
                available = ", ".join(service_map.keys())
                return (
                    f"'{service}'는 지원하지 않는 서비스입니다. "
                    f"지원 서비스: {available}"
                )

            if info["type"] == "oauth":
                provider = "google" if "google" in key else "microsoft"
                url = f"/api/oauth/start/{provider}?scopes={info['scopes']}"
                return (
                    f"\U0001f517 {info['name']} 연결하기\n\n"
                    f"아래 링크를 클릭하여 인증을 완료하세요:\n"
                    f"[OPEN_URL]{url}[/OPEN_URL]\n\n"
                    f"인증이 완료되면 자동으로 연동됩니다."
                )
            else:
                return (
                    f"\U0001f517 {info['name']} 연결하기\n\n"
                    f"Settings > Integrations에서 API 키를 입력하세요.\n"
                    f"또는 채팅에서 API 키를 알려주시면 바로 연결합니다."
                )

        # Collect all tools
        self._tools = [
            task_create,
            task_list,
            task_update,
            task_delete,
            event_create,
            event_list,
            event_update,
            event_delete,
            reminder_set,
            contact_search,
            contact_create,
            file_search,
            file_list,
            message_search,
            service_connect,
        ]

    def get_tools(self) -> list:
        return self._tools
