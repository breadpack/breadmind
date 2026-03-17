"""Domain model unit tests."""
from datetime import datetime, timezone
import pytest


def test_task_defaults():
    from breadmind.personal.models import Task
    task = Task(id="t1", title="Buy milk")
    assert task.status == "pending"
    assert task.priority == "medium"
    assert task.source == "builtin"
    assert task.due_at is None
    assert task.tags == []
    assert task.parent_id is None
    assert task.created_at.tzinfo == timezone.utc


def test_task_with_all_fields():
    from breadmind.personal.models import Task
    now = datetime.now(timezone.utc)
    task = Task(id="t2", title="Deploy v2", description="Production deployment",
        status="in_progress", priority="urgent", due_at=now,
        recurrence="FREQ=WEEKLY;BYDAY=MO", tags=["infra", "deploy"],
        source="jira", source_id="PROJ-123", assignee="alice", parent_id="t1")
    assert task.status == "in_progress"
    assert task.source_id == "PROJ-123"
    assert task.recurrence == "FREQ=WEEKLY;BYDAY=MO"


def test_event_defaults():
    from breadmind.personal.models import Event
    now = datetime.now(timezone.utc)
    event = Event(id="e1", title="Standup", start_at=now, end_at=now)
    assert event.all_day is False
    assert event.reminder_minutes == [15]
    assert event.source == "builtin"
    assert event.attendees == []


def test_contact_platform_ids():
    from breadmind.personal.models import Contact
    contact = Contact(id="c1", name="Bob", platform_ids={"telegram": "123", "slack": "U456"})
    assert contact.platform_ids["telegram"] == "123"
    assert contact.email is None


def test_file_defaults():
    from breadmind.personal.models import File
    f = File(id="f1", name="report.pdf", path_or_url="/tmp/report.pdf", mime_type="application/pdf")
    assert f.source == "local"
    assert f.size_bytes == 0


def test_message_defaults():
    from breadmind.personal.models import Message
    msg = Message(id="m1", content="Hello", sender="alice", channel="general", platform="slack")
    assert msg.thread_id is None
    assert msg.attachments == []


def test_parse_recurrence_shorthand():
    from breadmind.personal.models import normalize_recurrence
    assert normalize_recurrence("daily") == "FREQ=DAILY"
    assert normalize_recurrence("weekly") == "FREQ=WEEKLY"
    assert normalize_recurrence("monthly") == "FREQ=MONTHLY"
    assert normalize_recurrence("FREQ=WEEKLY;BYDAY=MO") == "FREQ=WEEKLY;BYDAY=MO"
    assert normalize_recurrence(None) is None
