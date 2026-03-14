import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

@dataclass
class IncomingMessage:
    text: str
    user_id: str
    channel_id: str
    platform: str       # "slack" | "discord" | "telegram" | "web"
    is_approval: bool = False
    approval_action_id: str | None = None
    approved: bool | None = None

@dataclass
class OutgoingMessage:
    text: str
    channel_id: str
    platform: str

@dataclass
class ApprovalRequest:
    action_id: str
    action_name: str
    params: dict
    channel_id: str
    platform: str
    user_id: str

class MessengerGateway(ABC):
    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...

    @abstractmethod
    async def send(self, channel_id: str, text: str):
        ...

    @abstractmethod
    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        """Returns an action_id for tracking the approval."""
        ...

class MessageRouter:
    def __init__(self):
        self._gateways: dict[str, MessengerGateway] = {}
        self._message_handler: Callable[[IncomingMessage], Any] | None = None
        self._allowed_users: dict[str, list[str]] = {}  # platform -> [user_ids]

    def register_gateway(self, platform: str, gateway: MessengerGateway):
        self._gateways[platform] = gateway

    def set_message_handler(self, handler: Callable[[IncomingMessage], Any]):
        self._message_handler = handler

    def set_allowed_users(self, platform: str, user_ids: list[str]):
        self._allowed_users[platform] = user_ids

    def is_authorized(self, platform: str, user_id: str) -> bool:
        allowed = self._allowed_users.get(platform, [])
        if not allowed:  # empty list = allow all
            return True
        return user_id in allowed

    async def handle_message(self, msg: IncomingMessage) -> str | None:
        if not self.is_authorized(msg.platform, msg.user_id):
            logger.warning(f"Unauthorized message from {msg.platform}/{msg.user_id}")
            return None

        if self._message_handler:
            if asyncio.iscoroutinefunction(self._message_handler):
                return await self._message_handler(msg)
            return self._message_handler(msg)
        return None

    async def send_message(self, platform: str, channel_id: str, text: str):
        gw = self._gateways.get(platform)
        if gw:
            await gw.send(channel_id, text)
        else:
            logger.error(f"No gateway for platform: {platform}")

    async def broadcast(self, text: str, platforms: list[str] | None = None, channels: dict[str, str] | None = None):
        """Send to all registered gateways or specific ones."""
        targets = platforms or list(self._gateways.keys())
        for platform in targets:
            gw = self._gateways.get(platform)
            if gw and channels and platform in channels:
                await gw.send(channels[platform], text)

    async def start_all(self):
        for name, gw in self._gateways.items():
            try:
                await gw.start()
                logger.info(f"Gateway started: {name}")
            except Exception as e:
                logger.error(f"Failed to start gateway {name}: {e}")

    async def stop_all(self):
        for name, gw in self._gateways.items():
            try:
                await gw.stop()
            except Exception as e:
                logger.error(f"Failed to stop gateway {name}: {e}")
