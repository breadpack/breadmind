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
            self._channel_names[cid] = ch.get("name", cid)
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
        since_ts = self.since.timestamp()
        until_ts = self.until.timestamp()
        include_threads = self.source_filter.get("include_threads", True)
        for cid in self.source_filter["channels"]:
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {
                    "channel": cid, "limit": 200,
                    "oldest": str(since_ts), "latest": str(until_ts),
                }
                if cursor:
                    params["cursor"] = cursor
                payload = await self._call_with_retry(
                    "conversations.history", **params)
                for msg in payload.get("messages", []):
                    ts = float(msg["ts"])
                    if ts < since_ts or ts >= until_ts:
                        continue
                    if include_threads and msg.get("thread_ts") == msg["ts"] \
                            and (msg.get("reply_count") or 0) > 0:
                        yield await self._build_thread_item(cid, msg)
                    else:
                        yield self._build_top_level_item(cid, msg)
                if not payload.get("has_more"):
                    break
                cursor = (payload.get("response_metadata") or {}).get(
                    "next_cursor")
                if not cursor:
                    break

    async def _call_with_retry(self, method: str, **params):
        backoffs = list(_BACKOFF_SECONDS)
        max_attempts = len(_BACKOFF_SECONDS) + 1  # 4 total tries
        for attempt in range(max_attempts):
            payload = await self._session.call(method, **params)
            if payload.get("_status") == 429 or (
                    payload.get("error") == "ratelimited"):
                if attempt == max_attempts - 1:
                    raise RuntimeError(
                        f"Slack {method} rate-limited after "
                        f"{max_attempts} attempts")
                import asyncio
                wait = int(payload["_retry_after"]
                           if "_retry_after" in payload
                           else (backoffs.pop(0) if backoffs
                                 else _BACKOFF_SECONDS[-1]))
                await asyncio.sleep(wait)
                continue
            return payload
        raise RuntimeError(
            f"Slack {method} unreachable after {max_attempts} attempts")

    def _build_top_level_item(self, cid: str, msg: dict) -> BackfillItem:
        ts = float(msg["ts"])
        created = datetime.fromtimestamp(ts, tz=timezone.utc)
        return BackfillItem(
            source_kind="slack_msg",
            source_native_id=f"{cid}:{msg['ts']}",
            source_uri=msg.get("permalink", f"slack://msg/{cid}/{msg['ts']}"),
            source_created_at=created,
            source_updated_at=datetime.fromtimestamp(
                float(msg.get("edited", {}).get("ts", msg["ts"])), tz=timezone.utc),
            title=f"[#{self._channel_names.get(cid, cid)}] "
                  f"{(msg.get('text') or '')[:80]}",
            body=msg.get("text", ""),
            author=msg.get("user") or msg.get("bot_id"),
            parent_ref=None,
            extra={"subtype": msg.get("subtype"),
                   "reaction_count": sum(r.get("count", 0)
                                         for r in msg.get("reactions", []) or []),
                   "reply_count": msg.get("reply_count", 0)},
        )

    async def _build_thread_item(self, cid: str, parent: dict) -> BackfillItem:
        thread_ts = parent["ts"]
        bodies: list[str] = [parent.get("text", "")]
        latest_edit_ts = float(
            parent.get("edited", {}).get("ts", parent["ts"]))
        cursor = None
        char_budget = 4000
        truncated = False
        while True:
            rp = await self._call_with_retry(
                "conversations.replies", channel=cid,
                ts=thread_ts, limit=200, cursor=cursor)
            for r in rp.get("messages", []):
                if r["ts"] == thread_ts:
                    continue
                ts = float(r["ts"])
                # client-side cut: replies API ignores oldest/latest
                if ts < self.since.timestamp() or ts >= self.until.timestamp():
                    continue
                text = r.get("text", "")
                if sum(len(b) for b in bodies) + len(text) > char_budget:
                    truncated = True
                    break
                bodies.append(text)
                latest_edit_ts = max(latest_edit_ts, ts)
            if truncated:
                break
            if not rp.get("has_more"):
                break
            cursor = (rp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
        return BackfillItem(
            source_kind="slack_msg",
            source_native_id=f"{cid}:{thread_ts}:thread",
            source_uri=parent.get("permalink",
                                  f"slack://msg/{cid}/{thread_ts}"),
            source_created_at=datetime.fromtimestamp(
                float(thread_ts), tz=timezone.utc),
            source_updated_at=datetime.fromtimestamp(
                latest_edit_ts, tz=timezone.utc),
            title=f"[#{self._channel_names.get(cid, cid)}] "
                  f"{(parent.get('text') or '')[:80]}",
            body="\n\n".join(bodies),
            author=parent.get("user"),
            parent_ref=None,  # this IS the parent
            extra={"reaction_count": sum(r.get("count", 0)
                                         for r in parent.get("reactions", []) or []),
                   "reply_count": parent.get("reply_count", 0),
                   "thread_truncated": truncated},
        )
