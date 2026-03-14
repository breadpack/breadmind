import logging
from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)

class SlackGateway(MessengerGateway):
    def __init__(self, bot_token: str, app_token: str | None = None, on_message=None):
        self._bot_token = bot_token
        self._app_token = app_token
        self._on_message = on_message
        self._app = None

    async def start(self):
        try:
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

            self._app = AsyncApp(token=self._bot_token)

            @self._app.message("")
            async def handle_message(message, say):
                if self._on_message:
                    from breadmind.messenger.router import IncomingMessage
                    msg = IncomingMessage(
                        text=message.get("text", ""),
                        user_id=message.get("user", ""),
                        channel_id=message.get("channel", ""),
                        platform="slack",
                    )
                    response = await self._on_message(msg)
                    if response:
                        await say(response)

            if self._app_token:
                handler = AsyncSocketModeHandler(self._app, self._app_token)
                await handler.start_async()
            logger.info("Slack gateway started.")
        except ImportError:
            logger.error("slack-bolt not installed. Run: pip install slack-bolt[async]")

    async def stop(self):
        logger.info("Slack gateway stopped.")

    async def send(self, channel_id: str, text: str):
        if self._app:
            await self._app.client.chat_postMessage(channel=channel_id, text=text)

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        import uuid
        action_id = str(uuid.uuid4())[:8]
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
