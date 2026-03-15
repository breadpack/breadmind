import asyncio
import json
import logging
import uuid
from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)


class SignalGateway(MessengerGateway):
    """Signal messenger gateway via signal-cli."""

    def __init__(self, phone_number: str, signal_cli_path: str = "signal-cli",
                 on_message=None, poll_interval: int = 5):
        self._phone_number = phone_number
        self._signal_cli = signal_cli_path
        self._on_message = on_message
        self._poll_interval = poll_interval
        self._connected = False
        self._enabled = True
        self._poll_task: asyncio.Task | None = None

    async def start(self):
        try:
            # Verify signal-cli is available
            proc = await asyncio.create_subprocess_exec(
                self._signal_cli, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                logger.error("signal-cli not available or not configured")
                return

            self._connected = True
            self._poll_task = asyncio.create_task(self._poll_messages())
            logger.info(f"Signal gateway started for {self._phone_number}")
        except FileNotFoundError:
            logger.error("signal-cli not found. Install from: https://github.com/AsamK/signal-cli")
        except Exception as e:
            logger.error(f"Signal gateway start failed: {e}")

    async def stop(self):
        self._connected = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def send(self, channel_id: str, text: str):
        """Send Signal message. channel_id is the recipient phone number."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self._signal_cli, "-a", self._phone_number,
                "send", "-m", text, channel_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"Signal send failed: {stderr.decode()}")
        except Exception as e:
            logger.error(f"Signal send error: {e}")

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        action_id = str(uuid.uuid4())[:8]
        text = (
            f"\U0001f510 Approval Required\n"
            f"Action: {action_name}\n"
            f"Params: {params}\n\n"
            f"Reply: approve {action_id}\n"
            f"Or: deny {action_id}"
        )
        await self.send(channel_id, text)
        return action_id

    async def _poll_messages(self):
        """Poll for new Signal messages using signal-cli receive."""
        while self._connected:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self._signal_cli, "-a", self._phone_number,
                    "receive", "--json", "-t", "1",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=self._poll_interval + 5
                )

                if stdout:
                    for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            await self._process_message(data)
                        except json.JSONDecodeError:
                            continue

            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Signal poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    async def _process_message(self, data: dict):
        """Process a single Signal message from JSON output."""
        if not self._on_message:
            return

        envelope = data.get("envelope", {})
        data_msg = envelope.get("dataMessage", {})
        body = data_msg.get("message", "")
        sender = envelope.get("sourceNumber", "") or envelope.get("source", "")

        if not body or not sender:
            return

        # Skip own messages
        if sender == self._phone_number:
            return

        from breadmind.messenger.router import IncomingMessage

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

        msg = IncomingMessage(
            text=body,
            user_id=sender,
            channel_id=sender,
            platform="signal",
            is_approval=is_approval,
            approval_action_id=approval_action_id,
            approved=approved,
        )
        response = await self._on_message(msg)
        if response:
            await self.send(sender, response)
