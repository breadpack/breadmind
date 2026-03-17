"""Universal domain models for the personal assistant.

All entities use source + source_id for bidirectional sync with external services.
Recurrence fields follow RFC 5545 RRULE format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_recurrence(value: str | None) -> str | None:
    """Normalize recurrence shorthand to RFC 5545 RRULE format."""
    if value is None:
        return None
    shorthands = {
        "daily": "FREQ=DAILY",
        "weekly": "FREQ=WEEKLY",
        "monthly": "FREQ=MONTHLY",
        "yearly": "FREQ=YEARLY",
    }
    return shorthands.get(value.lower(), value)


@dataclass
class Task:
    id: str
    title: str
    description: str | None = None
    status: Literal["pending", "in_progress", "done", "cancelled"] = "pending"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_at: datetime | None = None
    recurrence: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "builtin"
    source_id: str | None = None
    assignee: str | None = None
    parent_id: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class Event:
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    description: str | None = None
    all_day: bool = False
    location: str | None = None
    attendees: list[str] = field(default_factory=list)
    reminder_minutes: list[int] = field(default_factory=lambda: [15])
    recurrence: str | None = None
    source: str = "builtin"
    source_id: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Contact:
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    platform_ids: dict[str, str] = field(default_factory=dict)
    organization: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class File:
    id: str
    name: str
    path_or_url: str
    mime_type: str
    size_bytes: int = 0
    source: str = "local"
    source_id: str | None = None
    parent_folder: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Message:
    id: str
    content: str
    sender: str
    channel: str
    platform: str
    thread_id: str | None = None
    attachments: list[str] = field(default_factory=list)
    user_id: str = ""
    timestamp: datetime = field(default_factory=_utcnow)
