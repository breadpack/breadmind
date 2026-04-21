from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from breadmind.messenger.router import IncomingMessage
from breadmind.messenger.slack import SlackGateway

logger = logging.getLogger(__name__)


_PERMALINK_RE = re.compile(r"https://[^/]+/archives/[A-Z0-9]+/p\d+")


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
    ) -> None:
        super().__init__(bot_token=bot_token, app_token=app_token, on_message=on_message)
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
