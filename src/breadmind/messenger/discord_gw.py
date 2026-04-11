import logging
from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)

class DiscordGateway(MessengerGateway):
    def __init__(self, bot_token: str, on_message=None):
        super().__init__(platform="discord", on_message=on_message)
        self._bot_token = bot_token
        self._client = None

    async def start(self):
        try:
            import discord

            intents = discord.Intents.default()
            intents.message_content = True
            self._client = discord.Client(intents=intents)

            on_message_cb = self._on_message

            @self._client.event
            async def on_message(message):
                if message.author == self._client.user:
                    return
                if on_message_cb:
                    msg = self._create_incoming_message(
                        text=message.content,
                        user=str(message.author.id),
                        channel=str(message.channel.id),
                    )
                    response = await on_message_cb(msg)
                    if response:
                        await message.channel.send(response)

            import asyncio
            asyncio.create_task(self._client.start(self._bot_token))
            logger.info("Discord gateway started.")
        except ImportError:
            logger.error("discord.py not installed. Run: pip install discord.py")

    async def stop(self):
        if self._client:
            await self._client.close()

    async def send(self, channel_id: str, text: str):
        if self._client:
            channel = self._client.get_channel(int(channel_id))
            if channel:
                await channel.send(text)

    def _format_approval_message(self, action_name: str, params: dict, action_id: str) -> str:
        return f"**Approval Required**\nAction: `{action_name}`\nParams: `{params}`\nReact \u2705 to approve, \u274c to deny."
