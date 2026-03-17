"""Notion API adapter for task and page synchronization."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Task

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

# Mapping from Notion status names to internal status literals.
_STATUS_FROM_NOTION: dict[str, str] = {
    "Not started": "pending",
    "In progress": "in_progress",
    "Done": "done",
    "Cancelled": "cancelled",
}

_STATUS_TO_NOTION: dict[str, str] = {v: k for k, v in _STATUS_FROM_NOTION.items()}

_PRIORITY_FROM_NOTION: dict[str, str] = {
    "Low": "low",
    "Medium": "medium",
    "High": "high",
    "Urgent": "urgent",
}

_PRIORITY_TO_NOTION: dict[str, str] = {v: k for k, v in _PRIORITY_FROM_NOTION.items()}


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _page_to_task(page: dict[str, Any]) -> Task:
    """Convert a Notion page object into a Task dataclass."""
    props = page.get("properties", {})

    title = ""
    title_prop = props.get("Title") or props.get("Name")
    if title_prop and title_prop.get("title"):
        title = "".join(
            t.get("plain_text", "") for t in title_prop["title"]
        )

    status = "pending"
    status_prop = props.get("Status")
    if status_prop and status_prop.get("status"):
        status = _STATUS_FROM_NOTION.get(
            status_prop["status"].get("name", ""), "pending"
        )

    priority = "medium"
    priority_prop = props.get("Priority")
    if priority_prop and priority_prop.get("select"):
        priority = _PRIORITY_FROM_NOTION.get(
            priority_prop["select"].get("name", ""), "medium"
        )

    due_at: datetime | None = None
    due_prop = props.get("Due date") or props.get("Due")
    if due_prop and due_prop.get("date"):
        due_at = _parse_iso(due_prop["date"].get("start"))

    return Task(
        id=str(uuid.uuid4()),
        title=title,
        status=status,
        priority=priority,
        due_at=due_at,
        source="notion",
        source_id=page["id"],
    )


def _task_to_notion_properties(task: Task) -> dict[str, Any]:
    """Build Notion properties payload from a Task."""
    properties: dict[str, Any] = {
        "Title": {
            "title": [{"text": {"content": task.title}}],
        },
    }
    if task.status:
        properties["Status"] = {
            "status": {"name": _STATUS_TO_NOTION.get(task.status, "Not started")},
        }
    if task.priority:
        properties["Priority"] = {
            "select": {"name": _PRIORITY_TO_NOTION.get(task.priority, "Medium")},
        }
    if task.due_at:
        properties["Due date"] = {
            "date": {"start": task.due_at.isoformat()},
        }
    return properties


class NotionAdapter(ServiceAdapter):
    """Adapter for the Notion API (databases as task lists, pages as items)."""

    domain = "task"
    source = "notion"

    def __init__(self, database_id: str | None = None) -> None:
        self._api_key: str | None = None
        self._database_id = database_id
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self._api_key is None:
            raise RuntimeError("NotionAdapter is not authenticated")
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        url = f"{_BASE_URL}{path}"
        async with session.request(
            method, url, headers=self._headers(), json=json
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ------------------------------------------------------------------
    # ServiceAdapter interface
    # ------------------------------------------------------------------

    async def authenticate(self, credentials: dict) -> bool:
        self._api_key = credentials.get("api_key", "")
        if not self._api_key:
            return False

        if "database_id" in credentials:
            self._database_id = credentials["database_id"]

        try:
            # Step 1: Verify API key
            await self._request("GET", "/users/me")

            # Step 2: Verify database_id if provided
            if self._database_id:
                try:
                    await self._request("GET", f"/databases/{self._database_id}")
                except Exception:
                    raise ValueError(
                        f"Database ID '{self._database_id}' is invalid or not accessible. "
                        "Make sure the integration is connected to this database."
                    )

            return True
        except ValueError:
            raise  # Re-raise validation errors with clear message
        except Exception:
            self._api_key = None
            return False

    async def list_items(
        self, filters: dict | None = None, limit: int = 50
    ) -> list[Task]:
        if self._database_id is None:
            raise ValueError("database_id is required for list_items")
        body: dict[str, Any] = {"page_size": min(limit, 100)}
        if filters:
            body["filter"] = filters
        data = await self._request(
            "POST", f"/databases/{self._database_id}/query", json=body
        )
        return [_page_to_task(page) for page in data.get("results", [])]

    async def get_item(self, source_id: str) -> Task:
        data = await self._request("GET", f"/pages/{source_id}")
        return _page_to_task(data)

    async def create_item(self, entity: Task) -> str:
        if self._database_id is None:
            raise ValueError("database_id is required for create_item")
        body: dict[str, Any] = {
            "parent": {"database_id": self._database_id},
            "properties": _task_to_notion_properties(entity),
        }
        data = await self._request("POST", "/pages", json=body)
        return data["id"]

    async def update_item(self, source_id: str, changes: dict) -> bool:
        properties: dict[str, Any] = {}
        if "title" in changes:
            properties["Title"] = {
                "title": [{"text": {"content": changes["title"]}}],
            }
        if "status" in changes:
            properties["Status"] = {
                "status": {
                    "name": _STATUS_TO_NOTION.get(changes["status"], "Not started")
                },
            }
        if "priority" in changes:
            properties["Priority"] = {
                "select": {
                    "name": _PRIORITY_TO_NOTION.get(changes["priority"], "Medium")
                },
            }
        if "due_at" in changes:
            due_val = changes["due_at"]
            if isinstance(due_val, datetime):
                due_val = due_val.isoformat()
            properties["Due date"] = {"date": {"start": due_val}}
        await self._request(
            "PATCH", f"/pages/{source_id}", json={"properties": properties}
        )
        return True

    async def delete_item(self, source_id: str) -> bool:
        await self._request(
            "PATCH", f"/pages/{source_id}", json={"archived": True}
        )
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        """Sync tasks from the Notion database.

        If *since* is provided, only pages updated after that time are fetched.
        """
        filters: dict[str, Any] | None = None
        if since is not None:
            filters = {
                "timestamp": "last_edited_time",
                "last_edited_time": {"after": since.isoformat()},
            }
        tasks = await self.list_items(filters=filters, limit=100)
        return SyncResult(
            created=[t.source_id for t in tasks if t.source_id],
            updated=[],
            deleted=[],
            errors=[],
        )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
