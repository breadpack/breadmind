from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from breadmind.messenger.router import IncomingMessage
from breadmind.messenger.slack import SlackGateway

logger = logging.getLogger(__name__)


_PERMALINK_RE = re.compile(r"https://[^/]+/archives/[A-Z0-9]+/p\d+")


def _make_async_app(token: str):
    from slack_bolt.async_app import AsyncApp
    return AsyncApp(token=token)


class SlackEnhancedGateway(SlackGateway):
    """Enhanced Slack gateway: mentions, DMs, threads, buttons, streaming,
    permalink-formatted citations. Extends the base P1 SlackGateway."""

    UPVOTE_PREFIX = "kb_upvote_"
    DOWNVOTE_PREFIX = "kb_downvote_"
    BOOKMARK_PREFIX = "kb_bookmark_"

    def __init__(
        self,
        bot_token: str,
        bot_user_id: str,
        app_token: str | None = None,
        on_message: Callable | None = None,
        on_feedback: Callable | None = None,
        *,
        kb_db: Any | None = None,
    ) -> None:
        super().__init__(
            bot_token=bot_token,
            app_token=app_token,
            on_message=on_message,
            kb_db=kb_db,
        )
        self._bot_user_id = bot_user_id
        self._on_feedback = on_feedback

    def _strip_mention(self, text: str) -> str:
        prefix = f"<@{self._bot_user_id}>"
        if text.startswith(prefix):
            return text[len(prefix):].lstrip()
        return text

    def _build_incoming(self, event: dict[str, Any]) -> IncomingMessage:
        text = self._strip_mention(event.get("text", ""))
        return IncomingMessage(
            text=text,
            user_id=event.get("user", ""),
            channel_id=event.get("channel", ""),
            platform="slack",
            thread_ts=event.get("thread_ts"),
            is_dm=event.get("channel_type") == "im",
        )

    async def _handle_feedback_action(
        self, action_id: str, user_id: str,
    ) -> None:
        kind_map = {
            self.UPVOTE_PREFIX: "upvote",
            self.DOWNVOTE_PREFIX: "downvote",
            self.BOOKMARK_PREFIX: "bookmark",
        }
        for prefix, kind in kind_map.items():
            if action_id.startswith(prefix):
                answer_id = action_id[len(prefix):]
                if self._on_feedback is not None:
                    await self._on_feedback(kind, answer_id, user_id)
                return
        logger.debug("ignoring non-KB action_id=%s", action_id)

    def build_answer_blocks(
        self,
        body: str,
        answer_id: str,
        citations: list[tuple[str, str]],
        confidence_badge: str,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        ]
        if citations:
            cite_text = " ".join(f"<{uri}|{typ}>" for typ, uri in citations)
            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"📎 {cite_text}"},
                ],
            })
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"신뢰도: {confidence_badge}"},
            ],
        })
        blocks.append({
            "type": "actions",
            "elements": [
                {"type": "button",
                 "text": {"type": "plain_text", "text": "👍"},
                 "action_id": f"{self.UPVOTE_PREFIX}{answer_id}"},
                {"type": "button",
                 "text": {"type": "plain_text", "text": "👎"},
                 "action_id": f"{self.DOWNVOTE_PREFIX}{answer_id}"},
                {"type": "button",
                 "text": {"type": "plain_text", "text": "🔖 조직 KB로 저장"},
                 "action_id": f"{self.BOOKMARK_PREFIX}{answer_id}"},
            ],
        })
        return blocks

    @classmethod
    def format_citation_link(cls, source_type: str, uri: str) -> str:
        if _PERMALINK_RE.match(uri):
            return f"<{uri}|Slack 스레드>"
        return f"<{uri}|{source_type}>"

    async def stream_send(
        self,
        channel_id: str,
        chunks,  # AsyncIterator[str]
        flush_every: int = 3,
    ) -> str:
        """Post an initial message and update it as chunks arrive. Returns ts."""
        if self._app is None:
            return ""
        accumulated = ""
        ts = ""
        received = 0
        async for chunk in chunks:
            accumulated += chunk
            if not ts:
                resp = await self._app.client.chat_postMessage(
                    channel=channel_id, text=accumulated or " ",
                )
                ts = resp["ts"]
                received = 0
                continue
            received += 1
            if received >= flush_every:
                await self._app.client.chat_update(
                    channel=channel_id, ts=ts, text=accumulated,
                )
                received = 0
        if ts and received > 0:
            await self._app.client.chat_update(
                channel=channel_id, ts=ts, text=accumulated,
            )
        return ts

    async def start(self) -> None:  # type: ignore[override]
        self._app = _make_async_app(self._bot_token)

        @self._app.event("app_mention")
        async def _on_mention(event, say):
            inc = self._build_incoming(event)
            if self._on_message is not None:
                resp = await self._on_message(inc)
                if resp:
                    await say(resp)

        @self._app.event("message")
        async def _on_message_event(event, say):
            # Only DMs; channel messages come via app_mention
            if event.get("channel_type") != "im":
                return
            inc = self._build_incoming(event)
            if self._on_message is not None:
                resp = await self._on_message(inc)
                if resp:
                    await say(resp)

        @self._app.action(re.compile(r"^kb_(upvote|downvote|bookmark)_.+$"))
        async def _on_kb_action(ack, body):
            await ack()
            action = (body.get("actions") or [{}])[0]
            action_id = action.get("action_id", "")
            user_id = (body.get("user") or {}).get("id", "")
            await self._handle_feedback_action(action_id, user_id)

        # Wire KB review + feedback handlers if a kb_db was supplied.
        self._register_kb_handlers()

        if self._app_token:
            from slack_bolt.adapter.socket_mode.async_handler import (
                AsyncSocketModeHandler,
            )
            handler = AsyncSocketModeHandler(self._app, self._app_token)
            await handler.start_async()
        logger.info("SlackEnhancedGateway started.")
