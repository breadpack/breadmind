"""Jira REST API adapter for task management."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Task

logger = logging.getLogger(__name__)

# Jira status → BreadMind status mapping
_STATUS_MAP = {
    "To Do": "pending",
    "In Progress": "in_progress",
    "Done": "done",
}
_REVERSE_STATUS = {v: k for k, v in _STATUS_MAP.items()}

# Jira priority → BreadMind priority
_PRIORITY_MAP = {
    "Highest": "urgent",
    "High": "high",
    "Medium": "medium",
    "Low": "low",
    "Lowest": "low",
}


class JiraAdapter(ServiceAdapter):
    def __init__(self) -> None:
        self._base_url: str = ""
        self._auth_header: str = ""
        self._project_key: str = ""

    @property
    def domain(self) -> str:
        return "task"

    @property
    def source(self) -> str:
        return "jira"

    async def authenticate(self, credentials: dict) -> bool:
        self._base_url = credentials.get("base_url", "").rstrip("/")
        email = credentials.get("email", "")
        api_token = credentials.get("api_token", "")
        self._project_key = credentials.get("project_key", "")
        if not all([self._base_url, email, api_token]):
            return False
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._auth_header = f"Basic {token}"
        return True

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def list_items(
        self, filters: dict | None = None, limit: int = 50
    ) -> list[Task]:
        import aiohttp

        filters = filters or {}
        jql = f"project = {self._project_key}"
        if "status" in filters:
            jira_status = _REVERSE_STATUS.get(
                filters["status"], filters["status"]
            )
            jql += f' AND status = "{jira_status}"'
        jql += " ORDER BY created DESC"

        url = f"{self._base_url}/rest/api/3/search"
        params = {
            "jql": jql,
            "maxResults": limit,
            "fields": "summary,status,priority,duedate,assignee",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=self._headers(), params=params
            ) as resp:
                data = await resp.json()

        return [self._issue_to_task(issue) for issue in data.get("issues", [])]

    async def get_item(self, source_id: str) -> Task | None:
        import aiohttp

        url = f"{self._base_url}/rest/api/3/issue/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 404:
                    return None
                data = await resp.json()
        return self._issue_to_task(data)

    async def create_item(self, entity: Task) -> str:
        import aiohttp

        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": self._project_key},
                "summary": entity.title,
                "issuetype": {"name": "Task"},
            }
        }
        if entity.description:
            payload["fields"]["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": entity.description}
                        ],
                    }
                ],
            }
        if entity.due_at:
            payload["fields"]["duedate"] = entity.due_at.strftime("%Y-%m-%d")

        url = f"{self._base_url}/rest/api/3/issue"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=self._headers(), json=payload
            ) as resp:
                data = await resp.json()
        return data.get("key", data.get("id", ""))

    async def update_item(self, source_id: str, changes: dict) -> bool:
        import aiohttp

        fields: dict[str, Any] = {}
        if "title" in changes:
            fields["summary"] = changes["title"]
        if "due_at" in changes and changes["due_at"]:
            due = changes["due_at"]
            fields["duedate"] = (
                due.strftime("%Y-%m-%d") if isinstance(due, datetime) else due
            )

        if not fields:
            return False
        url = f"{self._base_url}/rest/api/3/issue/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.put(
                url, headers=self._headers(), json={"fields": fields}
            ) as resp:
                return resp.status in (200, 204)

    async def delete_item(self, source_id: str) -> bool:
        import aiohttp

        url = f"{self._base_url}/rest/api/3/issue/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=self._headers()) as resp:
                return resp.status in (200, 204)

    async def sync(self, since: datetime | None = None) -> SyncResult:
        return SyncResult(
            created=[],
            updated=[],
            deleted=[],
            errors=[],
            synced_at=datetime.now(timezone.utc),
        )

    def _issue_to_task(self, issue: dict) -> Task:
        fields = issue.get("fields", {})
        status_name = fields.get("status", {}).get("name", "To Do")
        priority_name = fields.get("priority", {}).get("name", "Medium")
        due_str = fields.get("duedate")
        due_at = (
            datetime.fromisoformat(due_str).replace(tzinfo=timezone.utc)
            if due_str
            else None
        )
        assignee = fields.get("assignee") or {}

        return Task(
            id=issue.get("key", issue.get("id", "")),
            title=fields.get("summary", ""),
            description="",
            status=_STATUS_MAP.get(status_name, "pending"),
            priority=_PRIORITY_MAP.get(priority_name, "medium"),
            due_at=due_at,
            source="jira",
            source_id=issue.get("key", ""),
            assignee=assignee.get("displayName") if assignee else None,
        )
