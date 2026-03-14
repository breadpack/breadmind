import logging
from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)

class TelegramGateway(MessengerGateway):
    def __init__(self, bot_token: str, on_message=None):
        self._bot_token = bot_token
        self._on_message = on_message
        self._app = None

    async def start(self):
        try:
            from telegram.ext import ApplicationBuilder, MessageHandler, filters

            self._app = ApplicationBuilder().token(self._bot_token).build()
            on_message_cb = self._on_message

            async def handle_message(update, context):
                if on_message_cb and update.message:
                    from breadmind.messenger.router import IncomingMessage
                    msg = IncomingMessage(
                        text=update.message.text or "",
                        user_id=str(update.effective_user.id),
                        channel_id=str(update.effective_chat.id),
                        platform="telegram",
                    )
                    response = await on_message_cb(msg)
                    if response:
                        await update.message.reply_text(response)

            self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            import asyncio
            asyncio.create_task(self._app.run_polling())
            logger.info("Telegram gateway started.")
        except ImportError:
            logger.error("python-telegram-bot not installed. Run: pip install python-telegram-bot")

    async def stop(self):
        if self._app:
            await self._app.stop()

    async def send(self, channel_id: str, text: str):
        if self._app:
            await self._app.bot.send_message(chat_id=int(channel_id), text=text)

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        import uuid
        action_id = str(uuid.uuid4())[:8]
        text = f"*Approval Required*\nAction: `{action_name}`\nParams: `{params}`"
        if self._app:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2705 Approve", callback_data=f"approve_{action_id}"),
                 InlineKeyboardButton("\u274c Deny", callback_data=f"deny_{action_id}")]
            ])
            await self._app.bot.send_message(chat_id=int(channel_id), text=text, reply_markup=keyboard)
        return action_id
