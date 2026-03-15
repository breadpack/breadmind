import asyncio
import logging
import uuid
from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)


class WhatsAppGateway(MessengerGateway):
    """WhatsApp messenger gateway via Twilio API."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str, on_message=None):
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number  # "whatsapp:+14155238886" format
        self._on_message = on_message
        self._client = None
        self._connected = False
        self._enabled = True

    async def start(self):
        try:
            from twilio.rest import Client
            self._client = Client(self._account_sid, self._auth_token)
            self._connected = True
            logger.info("WhatsApp gateway started (Twilio).")
        except ImportError:
            logger.error("twilio not installed. Run: pip install twilio")
        except Exception as e:
            logger.error(f"WhatsApp gateway start failed: {e}")

    async def stop(self):
        self._connected = False
        self._client = None

    async def send(self, channel_id: str, text: str):
        if not self._client:
            logger.error("WhatsApp client not initialized")
            return
        try:
            # channel_id should be "whatsapp:+1234567890" format
            to_number = channel_id if channel_id.startswith("whatsapp:") else f"whatsapp:{channel_id}"
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.messages.create(
                    body=text,
                    from_=self._from_number,
                    to=to_number,
                )
            )
        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        action_id = str(uuid.uuid4())[:8]
        text = (
            f"\U0001f510 *Approval Required*\n"
            f"Action: `{action_name}`\n"
            f"Params: `{params}`\n\n"
            f"Reply with: approve {action_id} or deny {action_id}"
        )
        await self.send(channel_id, text)
        return action_id

    async def handle_incoming_webhook(self, form_data: dict):
        """Handle incoming Twilio webhook data."""
        if not self._on_message:
            return
        body = form_data.get("Body", "")
        from_number = form_data.get("From", "")

        from breadmind.messenger.router import IncomingMessage

        # Check if this is an approval response
        is_approval = False
        approval_action_id = None
        approved = None
        body_lower = body.lower().strip()
        if body_lower.startswith("approve "):
            is_approval = True
            approval_action_id = body_lower.split(" ", 1)[1].strip()
            approved = True
        elif body_lower.startswith("deny "):
            is_approval = True
            approval_action_id = body_lower.split(" ", 1)[1].strip()
            approved = False

        msg = IncomingMessage(
            text=body,
            user_id=from_number,
            channel_id=from_number,
            platform="whatsapp",
            is_approval=is_approval,
            approval_action_id=approval_action_id,
            approved=approved,
        )
        response = await self._on_message(msg)
        if response:
            await self.send(from_number, response)
