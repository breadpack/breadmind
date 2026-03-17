"""CLI commands for personal assistant features."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Any


def register_commands(subparsers: Any) -> None:
    """Register personal assistant commands with the CLI parser."""

    # --- task ---
    task_parser = subparsers.add_parser("task", help="Manage tasks")
    task_sub = task_parser.add_subparsers(dest="task_action")

    task_list = task_sub.add_parser("list", help="List tasks")
    task_list.add_argument(
        "--status",
        choices=["pending", "in_progress", "done", "all"],
        default="pending",
    )
    task_list.add_argument(
        "--priority", choices=["low", "medium", "high", "urgent"],
    )

    task_add = task_sub.add_parser("add", help="Add a task")
    task_add.add_argument("title", help="Task title")
    task_add.add_argument("--due", help="Due date (ISO 8601)")
    task_add.add_argument(
        "--priority",
        default="medium",
        choices=["low", "medium", "high", "urgent"],
    )
    task_add.add_argument("--tags", help="Comma-separated tags")

    task_done = task_sub.add_parser("done", help="Mark task as done")
    task_done.add_argument("task_id", help="Task ID")

    task_del = task_sub.add_parser("delete", help="Delete a task")
    task_del.add_argument("task_id", help="Task ID")

    # --- event ---
    event_parser = subparsers.add_parser("event", help="Manage events")
    event_sub = event_parser.add_subparsers(dest="event_action")

    event_list = event_sub.add_parser("list", help="List upcoming events")
    event_list.add_argument("--days", type=int, default=7, help="Days ahead")

    event_add = event_sub.add_parser("add", help="Create an event")
    event_add.add_argument("title", help="Event title")
    event_add.add_argument(
        "--start", required=True, help="Start time (ISO 8601)",
    )
    event_add.add_argument("--end", help="End time (ISO 8601)")
    event_add.add_argument("--location", help="Location")

    event_del = event_sub.add_parser("delete", help="Delete an event")
    event_del.add_argument("event_id", help="Event ID")

    # --- contact ---
    contact_parser = subparsers.add_parser("contact", help="Manage contacts")
    contact_sub = contact_parser.add_subparsers(dest="contact_action")

    contact_search = contact_sub.add_parser("search", help="Search contacts")
    contact_search.add_argument("query", help="Search query")

    contact_add = contact_sub.add_parser("add", help="Add a contact")
    contact_add.add_argument("name", help="Contact name")
    contact_add.add_argument("--email", help="Email")
    contact_add.add_argument("--phone", help="Phone")
    contact_add.add_argument("--org", help="Organization")

    # --- agenda ---
    agenda_parser = subparsers.add_parser("agenda", help="Show daily agenda")
    agenda_parser.add_argument("--date", help="Date (ISO 8601)")

    # --- remind ---
    remind_parser = subparsers.add_parser("remind", help="Set a reminder")
    remind_parser.add_argument("message", help="Reminder message")
    remind_parser.add_argument(
        "--at", required=True, help="Remind at (ISO 8601)",
    )
    remind_parser.add_argument(
        "--recurrence", help="Recurrence (daily, weekly, monthly)",
    )


async def handle_command(args: Any, adapter_registry: Any) -> None:
    """Handle parsed CLI arguments."""
    command = getattr(args, "command", None)

    if command == "task":
        await _handle_task(args, adapter_registry)
    elif command == "event":
        await _handle_event(args, adapter_registry)
    elif command == "contact":
        await _handle_contact(args, adapter_registry)
    elif command == "agenda":
        await _handle_agenda(args, adapter_registry)
    elif command == "remind":
        await _handle_remind(args, adapter_registry)
    else:
        print(f"Unknown command: {command}")


async def _handle_task(args: Any, registry: Any) -> None:
    adapter = registry.get_adapter("task", "builtin")
    action = args.task_action

    if action == "list":
        filters: dict = {"user_id": "default"}
        if args.status and args.status != "all":
            filters["status"] = args.status
        if args.priority:
            filters["priority"] = args.priority
        tasks = await adapter.list_items(filters=filters)
        if not tasks:
            print("할 일이 없습니다.")
            return
        print(f"할 일 ({len(tasks)}개):")
        for t in tasks:
            icon = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "done": "[v]",
            }.get(t.status, "[ ]")
            due = (
                f" (마감: {t.due_at.strftime('%m/%d %H:%M')})"
                if t.due_at
                else ""
            )
            pri = f" [{t.priority}]" if t.priority != "medium" else ""
            print(f"  {icon} {t.title}{pri}{due}  [{t.id[:8]}]")

    elif action == "add":
        from breadmind.personal.models import Task

        due = _parse_dt(args.due) if args.due else None
        tags = (
            [t.strip() for t in args.tags.split(",")]
            if args.tags
            else []
        )
        task = Task(
            id="",
            title=args.title,
            priority=args.priority,
            due_at=due,
            tags=tags,
            user_id="default",
        )
        task_id = await adapter.create_item(task)
        print(f"할 일 추가: '{args.title}' [ID: {task_id[:8]}]")

    elif action == "done":
        await adapter.update_item(args.task_id, {"status": "done"})
        print(f"완료 처리: [{args.task_id[:8]}]")

    elif action == "delete":
        await adapter.delete_item(args.task_id)
        print(f"삭제: [{args.task_id[:8]}]")


async def _handle_event(args: Any, registry: Any) -> None:
    adapter = registry.get_adapter("event", "builtin")
    action = args.event_action

    if action == "list":
        now = datetime.now(timezone.utc)
        events = await adapter.list_items(filters={
            "user_id": "default",
            "start_after": now,
            "start_before": now + timedelta(days=args.days),
        })
        if not events:
            print("예정된 일정이 없습니다.")
            return
        print(f"일정 ({len(events)}개):")
        for e in events:
            loc = f" @ {e.location}" if e.location else ""
            end_str = e.end_at.strftime("%H:%M")
            start_str = e.start_at.strftime("%m/%d %H:%M")
            print(
                f"  * {start_str}~{end_str}"
                f" {e.title}{loc}  [{e.id[:8]}]"
            )

    elif action == "add":
        from breadmind.personal.models import Event

        start = _parse_dt(args.start)
        end = (
            _parse_dt(args.end) if args.end else start + timedelta(hours=1)
        )
        event = Event(
            id="",
            title=args.title,
            start_at=start,
            end_at=end,
            location=args.location,
            user_id="default",
        )
        event_id = await adapter.create_item(event)
        print(f"일정 추가: '{args.title}' [ID: {event_id[:8]}]")

    elif action == "delete":
        await adapter.delete_item(args.event_id)
        print(f"삭제: [{args.event_id[:8]}]")


async def _handle_contact(args: Any, registry: Any) -> None:
    adapters = registry.list_adapters("contact")
    if not adapters:
        print("연락처 어댑터가 설정되지 않았습니다.")
        return
    adapter = adapters[0]
    action = args.contact_action

    if action == "search":
        contacts = await adapter.list_items(
            filters={"user_id": "default", "query": args.query},
        )
        if not contacts:
            print(f"'{args.query}'에 대한 연락처를 찾을 수 없습니다.")
            return
        print(f"연락처 ({len(contacts)}개):")
        for c in contacts:
            parts = [f"  * {c.name}"]
            if c.email:
                parts.append(c.email)
            if c.phone:
                parts.append(c.phone)
            print(" | ".join(parts))

    elif action == "add":
        from breadmind.personal.models import Contact

        contact = Contact(
            id="",
            name=args.name,
            email=args.email,
            phone=args.phone,
            organization=args.org,
            user_id="default",
        )
        cid = await adapter.create_item(contact)
        print(
            f"연락처 추가: '{args.name}'"
            f" [ID: {cid[:8] if len(cid) > 8 else cid}]"
        )


async def _handle_agenda(args: Any, registry: Any) -> None:
    from breadmind.personal.cross_domain import CrossDomainQuery

    query = CrossDomainQuery(registry)
    date = _parse_dt(args.date) if args.date else None
    result = await query.daily_agenda("default", date)
    print(result["message"])


async def _handle_remind(args: Any, registry: Any) -> None:
    from breadmind.personal.models import Event, normalize_recurrence

    adapter = registry.get_adapter("event", "builtin")
    remind_at = _parse_dt(args.at)
    event = Event(
        id="",
        title=f"리마인더: {args.message}",
        start_at=remind_at,
        end_at=remind_at,
        reminder_minutes=[0],
        recurrence=normalize_recurrence(args.recurrence),
        user_id="default",
    )
    await adapter.create_item(event)
    recur = f" (반복: {args.recurrence})" if args.recurrence else ""
    print(
        f"리마인더 설정: '{args.message}'"
        f" ({remind_at.strftime('%m/%d %H:%M')}){recur}"
    )


def _parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 datetime string, defaulting to UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
