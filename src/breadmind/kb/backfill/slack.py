"""Slack backfill adapter — conversations.history + conversations.replies."""
from __future__ import annotations
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, ClassVar

from breadmind.kb.backfill.base import (
    BackfillItem, BackfillJob, Skipped,
)

_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 1800)
_SLACK_USER_ID_RE = re.compile(r"^[UW][A-Z0-9]{6,}$")


class SlackBackfillAdapter(BackfillJob):
    source_kind: ClassVar[str] = "slack_msg"

    def __init__(
        self, *, vault, credentials_ref: str,
        session=None, **kw,
    ) -> None:
        super().__init__(**kw)
        self._vault = vault
        self._credentials_ref = credentials_ref
        self._session = session
        self._membership_snapshot: frozenset[str] = frozenset()
        self._team_id: str = ""
        self._archived_channels: set[str] = set()
        self._channel_names: dict[str, str] = {}

    def instance_id_of(self, source_filter: dict[str, Any]) -> str:
        if not self._team_id:
            raise RuntimeError("instance_id_of called before prepare()")
        return self._team_id

    async def prepare(self) -> None:
        channels = self.source_filter.get("channels") or []
        if not channels:
            raise PermissionError("Slack source_filter.channels required")
        auth = await self._session.call("auth.test")
        if not auth.get("ok"):
            raise PermissionError(f"Slack auth.test failed: {auth}")
        self._team_id = auth["team_id"]
        members: set[str] = set()
        for cid in channels:
            info = await self._session.call("conversations.info", channel=cid)
            if not info.get("ok"):
                raise PermissionError(
                    f"channel {cid} info failed: {info}")
            ch = info["channel"]
            if ch.get("is_archived"):
                raise PermissionError(
                    f"channel {cid} archived since dry-run; "
                    "re-run dry-run to refresh and try again.")
            # conversations.members pagination
            cursor: str | None = None
            while True:
                payload = await self._session.call(
                    "conversations.members", channel=cid, cursor=cursor)
                members.update(payload.get("members", []))
                cursor = (payload.get("response_metadata") or {}).get(
                    "next_cursor")
                if not cursor:
                    break
        self._membership_snapshot = frozenset(members)

    def filter(self, item: BackfillItem) -> bool:
        # Stub — full heuristics in Task 12.
        return True

    async def discover(self) -> AsyncIterator[BackfillItem]:
        # Stub — implementation in Task 11.
        if False:
            yield  # type: ignore[unreachable]
