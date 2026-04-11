import asyncio
import base64
import logging
from email.mime.text import MIMEText
from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)


class GmailGateway(MessengerGateway):
    """Gmail messenger gateway via Google Gmail API."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 on_message=None, poll_interval: int = 30):
        super().__init__(platform="gmail", on_message=on_message)
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._poll_interval = poll_interval
        self._service = None
        self._poll_task: asyncio.Task | None = None
        self._last_history_id: str | None = None
        self._user_email: str = ""

    async def start(self):
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials(
                token=None,
                refresh_token=self._refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self._client_id,
                client_secret=self._client_secret,
                scopes=["https://www.googleapis.com/auth/gmail.modify"],
            )

            self._service = await asyncio.get_event_loop().run_in_executor(
                None, lambda: build("gmail", "v1", credentials=creds)
            )

            # Get user email
            profile = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._service.users().getProfile(userId="me").execute()
            )
            self._user_email = profile.get("emailAddress", "")
            self._last_history_id = profile.get("historyId")

            self._connected = True
            # Start polling for new messages
            self._poll_task = asyncio.create_task(self._poll_messages())
            logger.info(f"Gmail gateway started for {self._user_email}")
        except ImportError:
            logger.error("google-api-python-client not installed. Run: pip install google-api-python-client google-auth-oauthlib")
        except Exception as e:
            logger.error(f"Gmail gateway start failed: {e}")

    async def stop(self):
        self._connected = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._service = None

    async def send(self, channel_id: str, text: str):
        """Send email. channel_id is the recipient email address."""
        if not self._service:
            logger.error("Gmail service not initialized")
            return
        try:
            message = MIMEText(text)
            message["to"] = channel_id
            message["from"] = self._user_email
            message["subject"] = "BreadMind Notification"

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._service.users().messages().send(
                    userId="me", body={"raw": raw}
                ).execute()
            )
        except Exception as e:
            logger.error(f"Gmail send failed: {e}")

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        action_id = self._generate_action_id()
        text = (
            f"Approval Required\n"
            f"==================\n"
            f"Action: {action_name}\n"
            f"Params: {params}\n\n"
            f"Reply with: approve {action_id}\n"
            f"Or reply with: deny {action_id}"
        )
        # Send as email with subject indicating approval
        if self._service:
            try:
                message = MIMEText(text)
                message["to"] = channel_id
                message["from"] = self._user_email
                message["subject"] = f"[BreadMind] Approval Required: {action_name}"

                raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._service.users().messages().send(
                        userId="me", body={"raw": raw}
                    ).execute()
                )
            except Exception as e:
                logger.error(f"Gmail approval request failed: {e}")
        return action_id

    async def _poll_messages(self):
        """Poll for new incoming messages."""
        while self._connected:
            try:
                await asyncio.sleep(self._poll_interval)
                if not self._service or not self._last_history_id:
                    continue

                history = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._service.users().history().list(
                        userId="me",
                        startHistoryId=self._last_history_id,
                        historyTypes=["messageAdded"],
                    ).execute()
                )

                new_history_id = history.get("historyId")
                if new_history_id:
                    self._last_history_id = new_history_id

                for record in history.get("history", []):
                    for msg_added in record.get("messagesAdded", []):
                        msg_data = msg_added.get("message", {})
                        msg_id = msg_data.get("id")
                        if msg_id:
                            await self._process_message(msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Gmail poll error: {e}")

    async def _process_message(self, msg_id: str):
        """Process a single incoming message."""
        if not self._service or not self._on_message:
            return
        try:
            msg = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                ).execute()
            )

            # Extract sender and body
            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = headers.get("from", "")
            # Skip messages from self
            if self._user_email and self._user_email in sender:
                return

            body = ""
            payload = msg.get("payload", {})
            if "body" in payload and payload["body"].get("data"):
                body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
            elif "parts" in payload:
                for part in payload["parts"]:
                    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                        break

            if not body.strip():
                return

            # Check for approval responses
            is_approval = False
            approval_action_id = None
            approved = None
            body_lower = body.lower().strip()
            if body_lower.startswith("approve "):
                is_approval = True
                approval_action_id = body_lower.split(" ", 1)[1].strip().split()[0]
                approved = True
            elif body_lower.startswith("deny "):
                is_approval = True
                approval_action_id = body_lower.split(" ", 1)[1].strip().split()[0]
                approved = False

            incoming = self._create_incoming_message(
                text=body.strip(),
                user=sender,
                channel=sender,
                is_approval=is_approval,
                approval_action_id=approval_action_id,
                approved=approved,
            )
            response = await self._on_message(incoming)
            if response:
                await self.send(sender, response)

        except Exception as e:
            logger.debug(f"Gmail process message error: {e}")
