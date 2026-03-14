import logging
from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)

class DiscordGateway(MessengerGateway):
    def __init__(self, bot_token: str, on_message=None):
        self._bot_token = bot_token
        self._on_message = on_message
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
                    from breadmind.messenger.router import IncomingMessage
                    msg = IncomingMessage(
                        text=message.content,
                        user_id=str(message.author.id),
                        channel_id=str(message.channel.id),
                        platform="discord",
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

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        import uuid
        action_id = str(uuid.uuid4())[:8]
        text = f"**Approval Required**\nAction: `{action_name}`\nParams: `{params}`\nReact \u2705 to approve, \u274c to deny."
        await self.send(channel_id, text)
        return action_id
