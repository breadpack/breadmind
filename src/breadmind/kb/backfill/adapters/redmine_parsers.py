"""Pure JSON → dataclass parsers for Redmine REST API responses.

Kept separate from redmine_client.py to keep each file under 500 LOC.
No I/O or network code lives here — only parsing logic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from breadmind.kb.backfill.adapters.redmine_types import (
    RedmineAttachment,
    RedmineCustomField,
    RedmineIssue,
    RedmineJournal,
    RedmineStatusRef,
    RedmineUserRef,
)


def parse_dt(s: str | None) -> datetime | None:
    """Parse ISO-8601 string from Redmine (``Z`` or ``+00:00``) → UTC datetime."""
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def require_dt(s: str | None, field_name: str) -> datetime:
    dt = parse_dt(s)
    if dt is None:
        raise ValueError(f"Redmine field {field_name!r} is missing or null")
    return dt


def parse_user_ref(d: dict | None) -> RedmineUserRef | None:
    if not d:
        return None
    return RedmineUserRef(
        id=d["id"],
        name=d.get("name", ""),
        login=d.get("login"),
    )


def parse_journal(j: dict) -> RedmineJournal:
    return RedmineJournal(
        id=j["id"],
        created_on=require_dt(j.get("created_on"), "journal.created_on"),
        notes=j.get("notes") or "",
        private_notes=bool(j.get("private_notes", False)),
        user=parse_user_ref(j.get("user")),
        details=j.get("details") or [],
    )


def parse_attachment(a: dict) -> RedmineAttachment:
    return RedmineAttachment(
        id=a["id"],
        filename=a.get("filename", ""),
        filesize=a.get("filesize", 0),
        content_type=a.get("content_type", ""),
        content_url=a.get("content_url", ""),
        created_on=require_dt(a.get("created_on"), "attachment.created_on"),
        author=parse_user_ref(a.get("author")),
        description=a.get("description") or "",
    )


def parse_issue(d: dict) -> RedmineIssue:
    status_raw = d.get("status") or {}
    status = RedmineStatusRef(
        id=status_raw.get("id", 0),
        name=status_raw.get("name", ""),
        is_closed=status_raw.get("is_closed"),  # None on pre-4.x
    )
    tracker_raw = d.get("tracker") or {}
    project_raw = d.get("project") or {}
    custom_fields = [
        RedmineCustomField(
            id=cf["id"], name=cf.get("name", ""), value=cf.get("value")
        )
        for cf in (d.get("custom_fields") or [])
    ]
    return RedmineIssue(
        id=d["id"],
        subject=d.get("subject", ""),
        description=d.get("description") or "",
        created_on=require_dt(d.get("created_on"), "issue.created_on"),
        updated_on=require_dt(d.get("updated_on"), "issue.updated_on"),
        project_id=project_raw.get("id", 0),
        status=status,
        author=parse_user_ref(d.get("author")),
        tracker_name=tracker_raw.get("name", ""),
        journals=[parse_journal(j) for j in (d.get("journals") or [])],
        attachments=[parse_attachment(a) for a in (d.get("attachments") or [])],
        custom_fields=custom_fields,
    )
