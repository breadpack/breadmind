"""Google Calendar API adapter."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Event

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarAdapter(ServiceAdapter):
    """Adapter bridging Google Calendar API v3 to BreadMind Event domain."""

    def __init__(
        self,
        oauth_manager: Any,
        calendar_id: str = "primary",
        user_id: str = "default",
    ) -> None:
        self._oauth = oauth_manager
        self._calendar_id = calendar_id
        self._user_id = user_id

    @property
    def domain(self) -> str:
        return "event"

    @property
    def source(self) -> str:
        return "google_calendar"

    async def _get_headers(self) -> dict[str, str] | None:
        creds = await self._oauth.get_credentials("google", self._user_id)
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
            "maxResults": limit,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        if "start_after" in filters:
            params["timeMin"] = filters["start_after"].isoformat()
        if "start_before" in filters:
            params["timeMax"] = filters["start_before"].isoformat()

        url = f"{API_BASE}/calendars/{self._calendar_id}/events"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                data = await resp.json()

        return [self._to_event(item) for item in data.get("items", [])]

    async def get_item(self, source_id: str) -> Event | None:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            return None

        url = f"{API_BASE}/calendars/{self._calendar_id}/events/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 404:
                    return None
                return self._to_event(await resp.json())

    async def create_item(self, entity: Event) -> str:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            raise RuntimeError("Not authenticated with Google")

        body = self._to_google_event(entity)
        url = f"{API_BASE}/calendars/{self._calendar_id}/events"
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
            body["summary"] = changes["title"]
        if "location" in changes:
            body["location"] = changes["location"]
        if "start_at" in changes:
            body["start"] = {"dateTime": changes["start_at"].isoformat()}
        if "end_at" in changes:
            body["end"] = {"dateTime": changes["end_at"].isoformat()}
        if "description" in changes:
            body["description"] = changes["description"]
        if not body:
            return False

        url = f"{API_BASE}/calendars/{self._calendar_id}/events/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                url, headers=headers, json=body
            ) as resp:
                return resp.status == 200

    async def delete_item(self, source_id: str) -> bool:
        import aiohttp

        headers = await self._get_headers()
        if not headers:
            return False

        url = f"{API_BASE}/calendars/{self._calendar_id}/events/{source_id}"
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as resp:
                return resp.status in (200, 204)

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
        start_dt = self._parse_gcal_datetime(start)
        end_dt = self._parse_gcal_datetime(end)
        all_day = "date" in start and "dateTime" not in start
        attendees = [
            a.get("email", "") for a in item.get("attendees", [])
        ]
        reminders = item.get("reminders", {})
        reminder_mins = [
            r.get("minutes", 15)
            for r in reminders.get("overrides", [])
        ] or [15]

        recurrence_list = item.get("recurrence")
        recurrence = recurrence_list[0] if recurrence_list else None

        return Event(
            id=item.get("id", ""),
            title=item.get("summary", ""),
            description=item.get("description"),
            start_at=start_dt,
            end_at=end_dt,
            all_day=all_day,
            location=item.get("location"),
            attendees=attendees,
            reminder_minutes=reminder_mins,
            recurrence=recurrence,
            source="google_calendar",
            source_id=item.get("id", ""),
        )

    def _to_google_event(self, entity: Event) -> dict:
        body: dict[str, Any] = {"summary": entity.title}
        if entity.description:
            body["description"] = entity.description
        if entity.all_day:
            body["start"] = {"date": entity.start_at.strftime("%Y-%m-%d")}
            body["end"] = {"date": entity.end_at.strftime("%Y-%m-%d")}
        else:
            body["start"] = {"dateTime": entity.start_at.isoformat()}
            body["end"] = {"dateTime": entity.end_at.isoformat()}
        if entity.location:
            body["location"] = entity.location
        if entity.attendees:
            body["attendees"] = [{"email": a} for a in entity.attendees]
        return body

    @staticmethod
    def _parse_gcal_datetime(dt_obj: dict) -> datetime:
        if "dateTime" in dt_obj:
            return datetime.fromisoformat(
                dt_obj["dateTime"].replace("Z", "+00:00")
            )
        elif "date" in dt_obj:
            return datetime.strptime(dt_obj["date"], "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        return datetime.now(timezone.utc)
