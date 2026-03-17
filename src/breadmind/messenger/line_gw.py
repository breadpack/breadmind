"""LINE Messaging API gateway."""
from __future__ import annotations

import logging
import uuid
from typing import Callable

from breadmind.messenger.router import MessengerGateway, IncomingMessage

logger = logging.getLogger(__name__)

API_BASE = "https://api.line.me/v2/bot"


class LINEGateway(MessengerGateway):
    def __init__(self, channel_token: str, channel_secret: str = "", on_message: Callable | None = None) -> None:
        self._channel_token = channel_token
        self._channel_secret = channel_secret
        self._on_message = on_message
        self._connected = False

    async def start(self) -> None:
        self._connected = True
        logger.info("LINE gateway started")

    async def stop(self) -> None:
        self._connected = False
        logger.info("LINE gateway stopped")

    async def send(self, channel_id: str, text: str) -> None:
        import aiohttp
        url = f"{API_BASE}/message/push"
        headers = {"Authorization": f"Bearer {self._channel_token}", "Content-Type": "application/json"}
        payload = {"to": channel_id, "messages": [{"type": "text", "text": text}]}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    logger.error("LINE send failed: %s", await resp.text())

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        action_id = str(uuid.uuid4())[:8]
        text = f"\U0001f510 \uc2b9\uc778 \uc694\uccad: {action_name}\n\ud30c\ub77c\ubbf8\ud130: {params}\nAction ID: {action_id}"
        await self.send(channel_id, text)
        return action_id

    async def handle_webhook(self, body: dict) -> list[str | None]:
        """Process LINE webhook events."""
        responses = []
        for event in body.get("events", []):
            if event.get("type") != "message" or event.get("message", {}).get("type") != "text":
                responses.append(None)
                continue
            msg = IncomingMessage(
                text=event["message"]["text"],
                user_id=event.get("source", {}).get("userId", ""),
                channel_id=event.get("source", {}).get("userId", ""),
                platform="line",
            )
            if self._on_message:
                resp = await self._on_message(msg)
                responses.append(resp)
                # Reply via reply token
                if resp and "replyToken" in event:
                    await self._reply(event["replyToken"], resp)
            else:
                responses.append(None)
        return responses

    async def _reply(self, reply_token: str, text: str) -> None:
        import aiohttp
        url = f"{API_BASE}/message/reply"
        headers = {"Authorization": f"Bearer {self._channel_token}", "Content-Type": "application/json"}
        payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    logger.error("LINE reply failed: %s", await resp.text())
