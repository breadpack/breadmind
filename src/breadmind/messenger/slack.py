import logging
from typing import Any

from breadmind.messenger.router import IncomingMessage, MessengerGateway

logger = logging.getLogger(__name__)

class SlackGateway(MessengerGateway):
    def __init__(
        self,
        bot_token: str,
        app_token: str | None = None,
        on_message=None,
        *,
        kb_db=None,
    ):
        super().__init__(platform="slack", on_message=on_message)
        self._bot_token = bot_token
        self._app_token = app_token
        self._app = None
        # Optional KB database handle. When present, ``start()`` wires the
        # review + feedback interactive handlers onto the AsyncApp so that
        # approve/reject/needs-edit/feedback button clicks from Slack reach
        # the KB pipeline. ``None`` keeps the gateway usable in the old
        # (non-KB) P1 deployment.
        self._kb_db = kb_db

    def _build_msg(self, message: dict[str, Any]) -> IncomingMessage:
        """Construct an IncomingMessage from a slack-bolt event dict.

        T8: extracts the workspace identifier (``team`` preferred, ``team_id``
        accepted as a fallback for older payload variants) into
        ``tenant_native_id``. Empty strings are normalized to ``None`` so the
        router skips the lookup for malformed payloads.
        """
        team_raw = message.get("team") or message.get("team_id")
        tenant_native_id = team_raw if team_raw else None
        return self._create_incoming_message(
            text=message.get("text", ""),
            user=message.get("user", ""),
            channel=message.get("channel", ""),
            tenant_native_id=tenant_native_id,
        )

    async def start(self):
        try:
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

            self._app = AsyncApp(token=self._bot_token)

            @self._app.message("")
            async def handle_message(message, say):
                if self._on_message:
                    msg = self._build_msg(message)
                    response = await self._on_message(msg)
                    if response:
                        await say(response)

            self._register_kb_handlers()

            if self._app_token:
                handler = AsyncSocketModeHandler(self._app, self._app_token)
                await handler.start_async()
            logger.info("Slack gateway started.")
        except ImportError:
            logger.error("slack-bolt not installed. Run: pip install slack-bolt[async]")

    def _register_kb_handlers(self) -> None:
        """Wire KB review + feedback handlers onto ``self._app`` if ``kb_db``
        was supplied at construction. Safe no-op when ``kb_db is None`` or the
        KB package is unavailable."""
        if self._kb_db is None or self._app is None:
            return
        try:
            from breadmind.kb.feedback import (
                FeedbackHandler,
                register_feedback_handlers,
            )
            from breadmind.kb.review_queue import ReviewQueue
            from breadmind.kb.slack_review_handlers import register_review_handlers

            queue = ReviewQueue(self._kb_db, self._app.client)
            register_review_handlers(self._app, queue=queue)
            register_feedback_handlers(
                self._app,
                handler=FeedbackHandler(self._kb_db, self._app.client),
            )
            logger.info("KB review + feedback handlers registered on Slack gateway.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("KB Slack handlers not registered: %s", exc)

    async def stop(self):
        logger.info("Slack gateway stopped.")

    async def send(self, channel_id: str, text: str):
        if self._app:
            await self._app.client.chat_postMessage(channel=channel_id, text=text)

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        action_id = self._generate_action_id()
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Approval Required*\nAction: `{action_name}`\nParams: `{params}`"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary", "action_id": f"approve_{action_id}"},
                {"type": "button", "text": {"type": "plain_text", "text": "Deny"}, "style": "danger", "action_id": f"deny_{action_id}"},
            ]},
        ]
        if self._app:
            await self._app.client.chat_postMessage(channel=channel_id, text=f"Approval: {action_name}", blocks=blocks)
        return action_id
