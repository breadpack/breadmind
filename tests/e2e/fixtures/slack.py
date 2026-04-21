"""In-memory AsyncWebClient stub for E2E tests."""
from __future__ import annotations

from typing import Any


class FakeSlackClient:
    def __init__(self) -> None:
        self.posted: list[dict[str, Any]] = []
        self.dms: list[dict[str, Any]] = []
        self._members: dict[str, set[str]] = {}

    def set_channel_members(self, channel_id: str, user_ids: set[str]) -> None:
        self._members[channel_id] = set(user_ids)

    async def chat_postMessage(self, *, channel: str, text: str, **_: Any) -> dict:
        self.posted.append({"channel": channel, "text": text})
        return {"ok": True, "ts": f"ts-{len(self.posted)}"}

    async def conversations_open(self, *, users: str, **_: Any) -> dict:
        return {"ok": True, "channel": {"id": f"D-{users}"}}

    async def conversations_members(self, *, channel: str, **_: Any) -> dict:
        return {"ok": True, "members": list(self._members.get(channel, set()))}

    async def users_info(self, *, user: str, **_: Any) -> dict:
        return {"ok": True, "user": {"id": user, "real_name": user}}

    async def dm(self, user: str, text: str) -> None:
        self.dms.append({"user": user, "text": text})
