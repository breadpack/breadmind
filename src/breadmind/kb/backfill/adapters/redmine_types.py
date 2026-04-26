"""Plain dataclasses representing Redmine REST JSON objects.

Kept separate from redmine.py (adapter) and redmine_client.py (HTTP) so each
module stays below 500 LOC and each class has a single responsibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RedmineStatusRef:
    id: int
    name: str
    is_closed: bool | None = None  # absent on Redmine < 4.x


@dataclass
class RedmineUserRef:
    id: int
    name: str
    login: str | None = None  # only present in full user objects


@dataclass
class RedmineTrackerRef:
    id: int
    name: str


@dataclass
class RedmineProjectRef:
    id: int
    name: str
    identifier: str | None = None


@dataclass
class RedmineCustomField:
    id: int
    name: str
    value: str | list[str] | None


@dataclass
class RedmineAttachment:
    id: int
    filename: str
    filesize: int
    content_type: str
    content_url: str
    created_on: datetime
    author: RedmineUserRef | None = None
    description: str = ""


@dataclass
class RedmineJournal:
    id: int
    created_on: datetime
    notes: str
    private_notes: bool = False
    user: RedmineUserRef | None = None
    details: list[dict] = field(default_factory=list)


@dataclass
class RedmineIssue:
    id: int
    subject: str
    description: str
    created_on: datetime
    updated_on: datetime
    project_id: int
    status: RedmineStatusRef
    author: RedmineUserRef | None = None
    tracker_name: str = ""
    journals: list[RedmineJournal] = field(default_factory=list)
    attachments: list[RedmineAttachment] = field(default_factory=list)
    custom_fields: list[RedmineCustomField] = field(default_factory=list)


@dataclass
class RedmineMembership:
    project_id: int
    user_id: int
    role_names: list[str] = field(default_factory=list)


@dataclass
class RedmineWikiPage:
    title: str
    project_id: int
    updated_on: datetime
    created_on: datetime | None  # may be absent in index; fetched from page
    text: str = ""
    version: int = 1
    author: RedmineUserRef | None = None
