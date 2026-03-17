"""LLM tool functions for personal assistant task/event/reminder management.

These functions are designed to be called by the LLM via the tool registry.
The `registry` (AdapterRegistry) and `user_id` parameters are injected via
functools.partial — they are NOT provided by the LLM.
"""
from __future__ import annotations

import functools
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from breadmind.personal.models import Contact, Event, File, Task, normalize_recurrence

if TYPE_CHECKING:
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.tools.registry import ToolRegistry


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


# ---------------------------------------------------------------------------
# Task tools
# ---------------------------------------------------------------------------

async def task_create(
    title: str,
    registry: AdapterRegistry,
    user_id: str,
    description: str | None = None,
    due_at: str | None = None,
    priority: str = "medium",
    tags: str | None = None,
) -> str:
    """Create a new task."""
    adapter = registry.get_adapter("task", "builtin")
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    task = Task(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        due_at=_parse_datetime(due_at),
        priority=priority,  # type: ignore[arg-type]
        tags=tag_list,
        user_id=user_id,
    )
    task_id = await adapter.create_item(task)
    return f"할 일 생성 완료: '{title}' (ID: {task_id})"


async def task_list(
    registry: AdapterRegistry,
    user_id: str,
    status: str | None = None,
    priority: str | None = None,
    due_before: str | None = None,
    tags: str | None = None,
) -> str:
    """List tasks with optional filters."""
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


async def task_update(
    task_id: str,
    registry: AdapterRegistry,
    status: str | None = None,
    title: str | None = None,
    due_at: str | None = None,
    priority: str | None = None,
) -> str:
    """Update an existing task."""
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


async def task_delete(
    task_id: str,
    registry: AdapterRegistry,
) -> str:
    """Delete a task."""
    adapter = registry.get_adapter("task", "builtin")
    await adapter.delete_item(task_id)
    return f"할 일 삭제 완료 (ID: {task_id})"


# ---------------------------------------------------------------------------
# Event tools
# ---------------------------------------------------------------------------

async def event_create(
    title: str,
    start_at: str,
    registry: AdapterRegistry,
    user_id: str,
    end_at: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    attendees: str | None = None,
    reminder_minutes: str | None = None,
    recurrence: str | None = None,
) -> str:
    """Create a new calendar event."""
    adapter = registry.get_adapter("event", "builtin")
    start_dt = _parse_datetime(start_at)
    if end_at:
        end_dt = _parse_datetime(end_at)
    else:
        end_dt = start_dt + timedelta(hours=1)  # type: ignore[operator]

    attendee_list = [a.strip() for a in attendees.split(",")] if attendees else []
    reminder_list = (
        [int(m.strip()) for m in reminder_minutes.split(",")]
        if reminder_minutes
        else [15]
    )

    event = Event(
        id=str(uuid.uuid4()),
        title=title,
        start_at=start_dt,  # type: ignore[arg-type]
        end_at=end_dt,  # type: ignore[arg-type]
        all_day=all_day,
        location=location,
        attendees=attendee_list,
        reminder_minutes=reminder_list,
        recurrence=normalize_recurrence(recurrence),
        user_id=user_id,
    )
    event_id = await adapter.create_item(event)
    return f"일정 생성 완료: '{title}' (ID: {event_id})"


async def event_list(
    registry: AdapterRegistry,
    user_id: str,
    start_after: str | None = None,
    start_before: str | None = None,
) -> str:
    """List calendar events with optional time filters."""
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


async def event_update(
    event_id: str,
    registry: AdapterRegistry,
    title: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    location: str | None = None,
) -> str:
    """Update an existing event."""
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


async def event_delete(
    event_id: str,
    registry: AdapterRegistry,
) -> str:
    """Delete an event."""
    adapter = registry.get_adapter("event", "builtin")
    await adapter.delete_item(event_id)
    return f"일정 삭제 완료 (ID: {event_id})"


# ---------------------------------------------------------------------------
# Reminder tool
# ---------------------------------------------------------------------------

async def reminder_set(
    message: str,
    remind_at: str,
    registry: AdapterRegistry,
    user_id: str,
    recurrence: str | None = None,
) -> str:
    """Set a reminder (implemented as an event with reminder_minutes=[0])."""
    adapter = registry.get_adapter("event", "builtin")
    remind_dt = _parse_datetime(remind_at)
    event = Event(
        id=str(uuid.uuid4()),
        title=f"[리마인더] {message}",
        start_at=remind_dt,  # type: ignore[arg-type]
        end_at=remind_dt,  # type: ignore[arg-type]
        reminder_minutes=[0],
        recurrence=normalize_recurrence(recurrence),
        user_id=user_id,
    )
    event_id = await adapter.create_item(event)
    return f"리마인더 설정 완료: '{message}' @ {remind_at} (ID: {event_id})"


# ---------------------------------------------------------------------------
# Contact tools
# ---------------------------------------------------------------------------


async def contact_search(
    query: str,
    registry: AdapterRegistry,
    user_id: str,
) -> str:
    """연락처를 검색합니다."""
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


async def contact_create(
    name: str,
    registry: AdapterRegistry,
    user_id: str,
    email: str | None = None,
    phone: str | None = None,
    organization: str | None = None,
) -> str:
    """연락처를 추가합니다."""
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


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------


async def file_search(
    query: str,
    registry: AdapterRegistry,
    user_id: str,
    source: str | None = None,
) -> str:
    """파일을 검색합니다."""
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
            filters={"user_id": user_id, "name_contains": query}, limit=10,
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


async def file_list(
    registry: AdapterRegistry,
    user_id: str,
    source: str | None = None,
) -> str:
    """파일 목록을 조회합니다."""
    return await file_search(
        query="", registry=registry, user_id=user_id, source=source,
    )


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_personal_tools(
    tool_registry: ToolRegistry,
    adapter_registry: AdapterRegistry,
    user_id: str,
) -> None:
    """Register all personal tools into the ToolRegistry.

    Uses functools.partial to bind `registry` and `user_id` so the LLM
    only needs to provide the domain-specific parameters.
    """
    from breadmind.tools.registry import tool as tool_decorator

    tool_defs = [
        (task_create, "할 일을 생성합니다. title 필수, description/due_at/priority/tags 선택."),
        (task_list, "할 일 목록을 조회합니다. status/priority/due_before/tags 필터 선택."),
        (task_update, "할 일을 업데이트합니다. task_id 필수, status/title/due_at/priority 선택."),
        (task_delete, "할 일을 삭제합니다. task_id 필수."),
        (event_create, "캘린더 일정을 생성합니다. title/start_at 필수."),
        (event_list, "캘린더 일정을 조회합니다. start_after/start_before 필터 선택."),
        (event_update, "캘린더 일정을 업데이트합니다. event_id 필수."),
        (event_delete, "캘린더 일정을 삭제합니다. event_id 필수."),
        (reminder_set, "리마인더를 설정합니다. message/remind_at 필수, recurrence 선택."),
        (contact_search, "연락처를 검색합니다. query 필수."),
        (contact_create, "연락처를 추가합니다. name 필수, email/phone/organization 선택."),
        (file_search, "파일을 검색합니다. query 필수, source 선택."),
        (file_list, "파일 목록을 조회합니다. source 선택."),
    ]

    for func, description in tool_defs:
        # Bind registry and user_id via partial
        bound = functools.partial(func, registry=adapter_registry, user_id=user_id)
        # Preserve the original function name
        functools.update_wrapper(bound, func)
        # Apply @tool decorator
        decorated = tool_decorator(description)(bound)
        tool_registry.register(decorated)
