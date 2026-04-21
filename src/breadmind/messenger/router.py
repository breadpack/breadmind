import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Any
from abc import ABC, abstractmethod

from breadmind.messenger.platforms import get_platform_configs, get_platform_names
from breadmind.utils.helpers import generate_short_id

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
    thread_ts: str | None = None
    is_dm: bool = False
    thread_ts: str | None = None
    is_dm: bool = False

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


def get_all_platform_configs() -> dict[str, dict]:
    """Return the full platform configuration dictionary."""
    return get_platform_configs()


async def emit_messenger_received(incoming: "IncomingMessage"):
    """Emit MESSENGER_RECEIVED hook chain and return the decision.

    Callers should honor block/reply and apply modify patches locally.
    """
    from breadmind.core.events import get_event_bus
    from breadmind.hooks import HookEvent, HookPayload

    payload = HookPayload(
        event=HookEvent.MESSENGER_RECEIVED,
        data={
            "text": incoming.text,
            "user_id": incoming.user_id,
            "channel_id": incoming.channel_id,
            "platform": incoming.platform,
            "is_approval": incoming.is_approval,
        },
    )
    return await get_event_bus().run_hook_chain(
        HookEvent.MESSENGER_RECEIVED, payload,
    )


class MessengerGateway(ABC):
    _connected: bool = False
    _enabled: bool = True

    def __init__(self, platform: str, on_message: Callable | None = None):
        """Common initialization for all gateways.

        Subclasses should call ``super().__init__(platform, on_message)`` or
        simply set ``_platform`` and ``_on_message`` themselves for backward
        compatibility.

        The provided ``on_message`` callback is wrapped so every incoming
        message first flows through the MESSENGER_RECEIVED hook chain before
        reaching the client callback.
        """
        self._platform = platform
        self._user_on_message = on_message
        self._on_message = self._make_wrapped_on_message() if on_message else None

    def _make_wrapped_on_message(self) -> Callable:
        user_cb = self._user_on_message

        async def _wrapped(incoming: "IncomingMessage"):
            decision = await emit_messenger_received(incoming)
            kind = getattr(decision, "kind", None)
            kind_value = kind.value if kind is not None else "proceed"
            if kind_value == "block":
                logger.info(
                    "MESSENGER_RECEIVED blocked by hook: %s",
                    getattr(decision, "reason", ""),
                )
                return
            if kind_value == "reply":
                # Reply semantics for messenger are platform-specific;
                # Phase 2 just drops the message and logs.
                logger.info(
                    "MESSENGER_RECEIVED reply decision (Phase 2: drop+log)",
                )
                return
            if kind_value == "modify":
                patch = getattr(decision, "patch", {}) or {}
                if "text" in patch:
                    incoming.text = patch["text"]
                if "user_id" in patch:
                    incoming.user_id = patch["user_id"]
                if "channel_id" in patch:
                    incoming.channel_id = patch["channel_id"]
            if user_cb is None:
                return
            result = user_cb(incoming)
            if asyncio.iscoroutine(result):
                return await result
            return result
        return _wrapped

    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...

    @abstractmethod
    async def send(self, channel_id: str, text: str):
        ...

    # --- concrete helper methods ---

    def _create_incoming_message(
        self, text: str, user: str, channel: str, **kwargs: Any,
    ) -> "IncomingMessage":
        """Factory for IncomingMessage with sensible defaults."""
        return IncomingMessage(
            text=text,
            user_id=user,
            channel_id=channel,
            platform=getattr(self, "_platform", "unknown"),
            **kwargs,
        )

    @staticmethod
    def _generate_action_id() -> str:
        """Generate a short UUID-based action ID."""
        return generate_short_id()

    async def ask_approval(
        self, channel_id: str, action_name: str, params: dict,
    ) -> str:
        """Default approval flow: format message, send it, return action_id.

        Subclasses can override ``_format_approval_message`` for
        platform-specific formatting or override this method entirely for
        richer UI (e.g. Slack blocks, Telegram inline keyboards).
        """
        action_id = self._generate_action_id()
        text = self._format_approval_message(action_name, params, action_id)
        await self.send(channel_id, text)
        return action_id

    def _format_approval_message(
        self, action_name: str, params: dict, action_id: str,
    ) -> str:
        """Override point for platform-specific approval formatting."""
        return (
            f"Approval Required\n"
            f"Action: {action_name}\n"
            f"Params: {params}\n"
            f"ID: {action_id}\n"
            f"Reply 'approve {action_id}' or 'deny {action_id}'."
        )

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

    def update_allowed_users(self, platform: str, users: list[str]):
        """Update allowed users for a messenger platform."""
        self._allowed_users[platform] = users

    def get_allowed_users(self) -> dict[str, list[str]]:
        """Return allowed users for all platforms."""
        return dict(self._allowed_users)

    def add_allowed_user(self, platform: str, user: str):
        if platform not in self._allowed_users:
            self._allowed_users[platform] = []
        if user not in self._allowed_users[platform]:
            self._allowed_users[platform].append(user)

    def remove_allowed_user(self, platform: str, user: str):
        if platform in self._allowed_users:
            self._allowed_users[platform] = [u for u in self._allowed_users[platform] if u != user]

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
                response = await self._message_handler(msg)
            else:
                response = self._message_handler(msg)

            # Intercept [REQUEST_INPUT] blocks for messenger channels
            if response and isinstance(response, str) and "[REQUEST_INPUT]" in response:
                response = await self._convert_request_input_to_url(
                    response, msg.platform, msg.channel_id,
                )
            return response
        return None

    async def _convert_request_input_to_url(
        self, response: str, platform: str, channel_id: str,
    ) -> str:
        """Replace [REQUEST_INPUT]...[/REQUEST_INPUT] blocks with external URLs."""
        match = re.search(
            r"\[REQUEST_INPUT\]([\s\S]*?)\[/REQUEST_INPUT\]",
            response,
        )
        if not match:
            return response

        try:
            form_json = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse REQUEST_INPUT JSON for messenger")
            return response

        from breadmind.web.routes.credential_input import get_token_store, _get_base_url

        store = get_token_store()
        result = store.create(
            form=form_json,
            callback={
                "platform": platform,
                "channel_id": channel_id,
                "message": "Credentials submitted successfully.",
            },
            base_url=_get_base_url(),
        )

        url = result["url"]
        # Remove the [REQUEST_INPUT] block from the response
        pre_text = response[:match.start()].strip()
        pre_text = pre_text.replace("[NEED_CREDENTIALS]", "").strip()

        link_msg = f"Please enter your credentials at the link below:\n{url}"
        if pre_text:
            return f"{pre_text}\n\n{link_msg}"
        return link_msg

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

    def get_platform_status(self) -> dict[str, dict]:
        """Return status for all platforms."""
        result = {}
        for name, gw in self._gateways.items():
            result[name] = {
                "connected": getattr(gw, '_connected', False),
                "enabled": getattr(gw, '_enabled', True),
                "allowed_users": self._allowed_users.get(name, []),
            }
        # Always include all platforms even if no gateway
        for p in get_platform_names():
            if p not in result:
                result[p] = {"connected": False, "enabled": False, "allowed_users": self._allowed_users.get(p, [])}
        return result

    def set_platform_enabled(self, platform: str, enabled: bool):
        """Enable/disable a platform."""
        gw = self._gateways.get(platform)
        if gw:
            gw._enabled = enabled

    def get_platform_config(self, platform: str) -> dict:
        """Get config needed for a platform (what tokens are required, etc)."""
        return get_platform_configs().get(platform, {"fields": []})

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
