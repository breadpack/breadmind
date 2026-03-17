"""GitHub Issues adapter for task management."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Task

logger = logging.getLogger(__name__)

_STATE_MAP = {"open": "pending", "closed": "done"}
_REVERSE_STATE = {
    "pending": "open",
    "in_progress": "open",
    "done": "closed",
    "cancelled": "closed",
}


class GitHubIssuesAdapter(ServiceAdapter):
    def __init__(self) -> None:
        self._token: str = ""
        self._owner: str = ""
        self._repo: str = ""

    @property
    def domain(self) -> str:
        return "task"

    @property
    def source(self) -> str:
        return "github"

    async def authenticate(self, credentials: dict) -> bool:
        self._token = credentials.get("token", "")
        self._owner = credentials.get("owner", "")
        self._repo = credentials.get("repo", "")
        return bool(self._token and self._owner and self._repo)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def list_items(
        self, filters: dict | None = None, limit: int = 50
    ) -> list[Task]:
        import aiohttp

        filters = filters or {}
        params: dict[str, Any] = {"per_page": limit, "state": "open"}
        if "status" in filters:
            params["state"] = _REVERSE_STATE.get(filters["status"], "open")
        if "tags" in filters:
            params["labels"] = ",".join(filters["tags"])

        url = (
            f"https://api.github.com/repos/{self._owner}/{self._repo}/issues"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=self._headers(), params=params
            ) as resp:
                data = await resp.json()
        return [self._issue_to_task(i) for i in data if "pull_request" not in i]

    async def get_item(self, source_id: str) -> Task | None:
        import aiohttp

        url = (
            f"https://api.github.com/repos/{self._owner}/{self._repo}"
            f"/issues/{source_id}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 404:
                    return None
                return self._issue_to_task(await resp.json())

    async def create_item(self, entity: Task) -> str:
        import aiohttp

        payload: dict[str, Any] = {"title": entity.title}
        if entity.description:
            payload["body"] = entity.description
        if entity.tags:
            payload["labels"] = entity.tags
        if entity.assignee:
            payload["assignees"] = [entity.assignee]

        url = (
            f"https://api.github.com/repos/{self._owner}/{self._repo}/issues"
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=self._headers(), json=payload
            ) as resp:
                data = await resp.json()
        return str(data.get("number", ""))

    async def update_item(self, source_id: str, changes: dict) -> bool:
        import aiohttp

        payload: dict[str, Any] = {}
        if "title" in changes:
            payload["title"] = changes["title"]
        if "status" in changes:
            payload["state"] = _REVERSE_STATE.get(changes["status"], "open")
        if "tags" in changes:
            payload["labels"] = changes["tags"]
        if not payload:
            return False

        url = (
            f"https://api.github.com/repos/{self._owner}/{self._repo}"
            f"/issues/{source_id}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                url, headers=self._headers(), json=payload
            ) as resp:
                return resp.status == 200

    async def delete_item(self, source_id: str) -> bool:
        # GitHub doesn't support deleting issues — close instead
        return await self.update_item(source_id, {"status": "done"})

    async def sync(self, since: datetime | None = None) -> SyncResult:
        return SyncResult(
            created=[],
            updated=[],
            deleted=[],
            errors=[],
            synced_at=datetime.now(timezone.utc),
        )

    def _issue_to_task(self, issue: dict) -> Task:
        labels = [
            l["name"] if isinstance(l, dict) else l
            for l in issue.get("labels", [])
        ]
        assignees = issue.get("assignees", [])
        priority = "high" if "priority:high" in labels else "medium"

        return Task(
            id=str(issue.get("number", "")),
            title=issue.get("title", ""),
            description=issue.get("body") or "",
            status=_STATE_MAP.get(issue.get("state", "open"), "pending"),
            priority=priority,
            tags=labels,
            source="github",
            source_id=str(issue.get("number", "")),
            assignee=assignees[0].get("login") if assignees else None,
        )
