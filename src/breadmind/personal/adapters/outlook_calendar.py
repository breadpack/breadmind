"""Microsoft Outlook Calendar adapter via Graph API."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Event

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookCalendarAdapter(ServiceAdapter):
    """Adapter bridging Microsoft Graph Calendar API to BreadMind Event domain."""

    def __init__(self, oauth_manager: Any) -> None:
        self._oauth = oauth_manager

    @property
    def domain(self) -> str:
        return "event"

    @property
    def source(self) -> str:
        return "outlook"

    async def _get_headers(self) -> dict[str, str] | None:
        creds = await self._oauth.get_credentials("microsoft")
        if not creds:
            return None
        return {
            "Authorization": f"Bearer {creds.access_token}",
            "Content-Type": "application/json",
        }

    async def authenticate(self, credentials: dict) -> bool:
        headers = await self._get_headers()
        return headers is not None

    async def list_items(
        self, filters: dict | None = None, limit: int = 50
    ) -> list[Event]:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            return []

        filters = filters or {}
        params: dict[str, Any] = {
            "$top": limit,
            "$orderby": "start/dateTime",
        }

        filter_parts: list[str] = []
        if "start_after" in filters:
            filter_parts.append(
                f"start/dateTime ge '{filters['start_after'].isoformat()}'"
            )
        if "start_before" in filters:
            filter_parts.append(
                f"start/dateTime le '{filters['start_before'].isoformat()}'"
            )
        if filter_parts:
            params["$filter"] = " and ".join(filter_parts)

        url = f"{GRAPH_BASE}/me/events"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                data = await resp.json()

        return [self._to_event(item) for item in data.get("value", [])]

    async def get_item(self, source_id: str) -> Event | None:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            return None

        url = f"{GRAPH_BASE}/me/events/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 404:
                    return None
                return self._to_event(await resp.json())

    async def create_item(self, entity: Event) -> str:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            raise RuntimeError("Not authenticated with Microsoft")

        body = self._to_graph_event(entity)
        url = f"{GRAPH_BASE}/me/events"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as resp:
                data = await resp.json()

        return data.get("id", "")

    async def update_item(self, source_id: str, changes: dict) -> bool:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            return False

        body: dict[str, Any] = {}
        if "title" in changes:
            body["subject"] = changes["title"]
        if "location" in changes:
            body["location"] = {"displayName": changes["location"]}
        if "start_at" in changes:
            body["start"] = {
                "dateTime": changes["start_at"].isoformat(),
                "timeZone": "UTC",
            }
        if "end_at" in changes:
            body["end"] = {
                "dateTime": changes["end_at"].isoformat(),
                "timeZone": "UTC",
            }
        if "description" in changes:
            body["body"] = {
                "contentType": "text",
                "content": changes["description"],
            }
        if not body:
            return False

        url = f"{GRAPH_BASE}/me/events/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=headers, json=body) as resp:
                return resp.status == 200

    async def delete_item(self, source_id: str) -> bool:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            return False

        url = f"{GRAPH_BASE}/me/events/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as resp:
                return resp.status == 204

    async def sync(self, since: datetime | None = None) -> SyncResult:
        events = await self.list_items(
            filters={"start_after": since} if since else None
        )
        return SyncResult(
            created=[e.id for e in events],
            updated=[],
            deleted=[],
            errors=[],
            synced_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def _to_event(self, item: dict) -> Event:
        start = item.get("start", {})
        end = item.get("end", {})
        start_dt = self._parse_graph_datetime(start)
        end_dt = self._parse_graph_datetime(end)
        is_all_day = item.get("isAllDay", False)
        attendees = [
            a.get("emailAddress", {}).get("address", "")
            for a in item.get("attendees", [])
        ]
        location = item.get("location", {}).get("displayName", "")

        return Event(
            id=item.get("id", ""),
            title=item.get("subject", ""),
            description=item.get("bodyPreview"),
            start_at=start_dt,
            end_at=end_dt,
            all_day=is_all_day,
            location=location or None,
            attendees=attendees,
            reminder_minutes=[item.get("reminderMinutesBeforeStart", 15)],
            source="outlook",
            source_id=item.get("id", ""),
        )

    def _to_graph_event(self, entity: Event) -> dict:
        body: dict[str, Any] = {
            "subject": entity.title,
            "start": {
                "dateTime": entity.start_at.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": entity.end_at.isoformat(),
                "timeZone": "UTC",
            },
            "isAllDay": entity.all_day,
        }
        if entity.description:
            body["body"] = {
                "contentType": "text",
                "content": entity.description,
            }
        if entity.location:
            body["location"] = {"displayName": entity.location}
        if entity.attendees:
            body["attendees"] = [
                {"emailAddress": {"address": a}, "type": "required"}
                for a in entity.attendees
            ]
        return body

    @staticmethod
    def _parse_graph_datetime(dt_obj: dict) -> datetime:
        dt_str = dt_obj.get("dateTime", "")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                pass
        return datetime.now(timezone.utc)
