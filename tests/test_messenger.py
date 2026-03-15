import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.messenger.router import MessageRouter, IncomingMessage, MessengerGateway

class MockGateway(MessengerGateway):
    def __init__(self):
        self.started = False
        self.stopped = False
        self.sent_messages = []

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def send(self, channel_id: str, text: str):
        self.sent_messages.append((channel_id, text))

    async def ask_approval(self, channel_id: str, action_name: str, params: dict) -> str:
        return "test_action_id"

@pytest.fixture
def router():
    return MessageRouter()

def test_register_gateway(router):
    gw = MockGateway()
    router.register_gateway("test", gw)
    assert "test" in router._gateways

def test_authorization_empty_list(router):
    assert router.is_authorized("slack", "any_user") is True

def test_authorization_allowed(router):
    router.set_allowed_users("slack", ["U123"])
    assert router.is_authorized("slack", "U123") is True
    assert router.is_authorized("slack", "U999") is False

@pytest.mark.asyncio
async def test_handle_message(router):
    handler = AsyncMock(return_value="response")
    router.set_message_handler(handler)
    msg = IncomingMessage(text="hello", user_id="U1", channel_id="C1", platform="slack")
    result = await router.handle_message(msg)
    assert result == "response"
    handler.assert_called_once()

@pytest.mark.asyncio
async def test_handle_unauthorized(router):
    router.set_allowed_users("slack", ["U123"])
    handler = AsyncMock(return_value="response")
    router.set_message_handler(handler)
    msg = IncomingMessage(text="hello", user_id="UNAUTHORIZED", channel_id="C1", platform="slack")
    result = await router.handle_message(msg)
    assert result is None
    handler.assert_not_called()

@pytest.mark.asyncio
async def test_send_message(router):
    gw = MockGateway()
    router.register_gateway("test", gw)
    await router.send_message("test", "C1", "hello")
    assert ("C1", "hello") in gw.sent_messages

@pytest.mark.asyncio
async def test_start_stop_all(router):
    gw = MockGateway()
    router.register_gateway("test", gw)
    await router.start_all()
    assert gw.started is True
    await router.stop_all()
    assert gw.stopped is True

# --- Dynamic allowed_users config tests ---

def test_update_allowed_users(router):
    router.update_allowed_users("slack", ["U1", "U2"])
    assert router._allowed_users["slack"] == ["U1", "U2"]

def test_update_allowed_users_replaces(router):
    router.update_allowed_users("slack", ["U1"])
    router.update_allowed_users("slack", ["U3", "U4"])
    assert router._allowed_users["slack"] == ["U3", "U4"]

def test_get_allowed_users(router):
    router.update_allowed_users("slack", ["U1"])
    router.update_allowed_users("discord", ["D1", "D2"])
    result = router.get_allowed_users()
    assert result == {"slack": ["U1"], "discord": ["D1", "D2"]}

def test_get_allowed_users_empty(router):
    assert router.get_allowed_users() == {}

def test_add_allowed_user(router):
    router.add_allowed_user("slack", "U1")
    assert router._allowed_users["slack"] == ["U1"]
    # Adding again should not duplicate
    router.add_allowed_user("slack", "U1")
    assert router._allowed_users["slack"] == ["U1"]

def test_add_allowed_user_new_platform(router):
    router.add_allowed_user("telegram", "T1")
    assert router._allowed_users["telegram"] == ["T1"]

def test_remove_allowed_user(router):
    router.update_allowed_users("slack", ["U1", "U2", "U3"])
    router.remove_allowed_user("slack", "U2")
    assert router._allowed_users["slack"] == ["U1", "U3"]

def test_remove_allowed_user_not_present(router):
    router.update_allowed_users("slack", ["U1"])
    router.remove_allowed_user("slack", "U999")
    assert router._allowed_users["slack"] == ["U1"]

def test_remove_allowed_user_no_platform(router):
    # Should not raise
    router.remove_allowed_user("nonexistent", "U1")

@pytest.mark.asyncio
async def test_broadcast(router):
    gw1 = MockGateway()
    gw2 = MockGateway()
    router.register_gateway("slack", gw1)
    router.register_gateway("discord", gw2)
    await router.broadcast("alert!", channels={"slack": "C1", "discord": "C2"})
    assert ("C1", "alert!") in gw1.sent_messages
    assert ("C2", "alert!") in gw2.sent_messages


# --- WhatsApp Gateway tests ---

class TestWhatsAppGateway:
    @pytest.fixture
    def whatsapp_gw(self):
        from breadmind.messenger.whatsapp_gw import WhatsAppGateway
        return WhatsAppGateway(
            account_sid="test_sid",
            auth_token="test_token",
            from_number="whatsapp:+14155238886",
        )

    def test_init(self, whatsapp_gw):
        assert whatsapp_gw._account_sid == "test_sid"
        assert whatsapp_gw._from_number == "whatsapp:+14155238886"
        assert whatsapp_gw._connected is False

    @pytest.mark.asyncio
    async def test_stop(self, whatsapp_gw):
        whatsapp_gw._connected = True
        await whatsapp_gw.stop()
        assert whatsapp_gw._connected is False
        assert whatsapp_gw._client is None

    @pytest.mark.asyncio
    async def test_ask_approval(self, whatsapp_gw):
        whatsapp_gw._client = MagicMock()
        action_id = await whatsapp_gw.ask_approval("whatsapp:+1234", "test_action", {"key": "val"})
        assert len(action_id) == 8

    @pytest.mark.asyncio
    async def test_handle_incoming_approval(self, whatsapp_gw):
        handler = AsyncMock(return_value="approved")
        whatsapp_gw._on_message = handler
        whatsapp_gw._client = MagicMock()
        await whatsapp_gw.handle_incoming_webhook({
            "Body": "approve abc123",
            "From": "whatsapp:+1234",
        })
        handler.assert_called_once()
        call_args = handler.call_args[0][0]
        assert call_args.is_approval is True
        assert call_args.approved is True

    @pytest.mark.asyncio
    async def test_handle_incoming_regular(self, whatsapp_gw):
        handler = AsyncMock(return_value="response")
        whatsapp_gw._on_message = handler
        whatsapp_gw._client = MagicMock()
        await whatsapp_gw.handle_incoming_webhook({
            "Body": "hello",
            "From": "whatsapp:+1234",
        })
        handler.assert_called_once()
        call_args = handler.call_args[0][0]
        assert call_args.is_approval is False


# --- Gmail Gateway tests ---

class TestGmailGateway:
    @pytest.fixture
    def gmail_gw(self):
        from breadmind.messenger.gmail_gw import GmailGateway
        return GmailGateway(
            client_id="test_id",
            client_secret="test_secret",
            refresh_token="test_token",
        )

    def test_init(self, gmail_gw):
        assert gmail_gw._client_id == "test_id"
        assert gmail_gw._poll_interval == 30
        assert gmail_gw._connected is False

    @pytest.mark.asyncio
    async def test_stop(self, gmail_gw):
        gmail_gw._connected = True
        await gmail_gw.stop()
        assert gmail_gw._connected is False
        assert gmail_gw._service is None

    @pytest.mark.asyncio
    async def test_ask_approval(self, gmail_gw):
        gmail_gw._service = MagicMock()
        gmail_gw._user_email = "test@example.com"
        mock_send = MagicMock()
        mock_send.execute.return_value = {}
        gmail_gw._service.users.return_value.messages.return_value.send.return_value = mock_send
        action_id = await gmail_gw.ask_approval("user@example.com", "test_action", {"key": "val"})
        assert len(action_id) == 8


# --- Signal Gateway tests ---

class TestSignalGateway:
    @pytest.fixture
    def signal_gw(self):
        from breadmind.messenger.signal_gw import SignalGateway
        return SignalGateway(phone_number="+1234567890")

    def test_init(self, signal_gw):
        assert signal_gw._phone_number == "+1234567890"
        assert signal_gw._signal_cli == "signal-cli"
        assert signal_gw._connected is False

    @pytest.mark.asyncio
    async def test_stop(self, signal_gw):
        signal_gw._connected = True
        await signal_gw.stop()
        assert signal_gw._connected is False

    @pytest.mark.asyncio
    async def test_process_message(self, signal_gw):
        handler = AsyncMock(return_value=None)
        signal_gw._on_message = handler
        data = {
            "envelope": {
                "sourceNumber": "+9876543210",
                "dataMessage": {"message": "hello signal"},
            }
        }
        await signal_gw._process_message(data)
        handler.assert_called_once()
        call_args = handler.call_args[0][0]
        assert call_args.text == "hello signal"
        assert call_args.platform == "signal"

    @pytest.mark.asyncio
    async def test_process_approval_message(self, signal_gw):
        handler = AsyncMock(return_value=None)
        signal_gw._on_message = handler
        data = {
            "envelope": {
                "sourceNumber": "+9876543210",
                "dataMessage": {"message": "approve abc123"},
            }
        }
        await signal_gw._process_message(data)
        call_args = handler.call_args[0][0]
        assert call_args.is_approval is True
        assert call_args.approved is True

    @pytest.mark.asyncio
    async def test_skip_own_messages(self, signal_gw):
        handler = AsyncMock()
        signal_gw._on_message = handler
        data = {
            "envelope": {
                "sourceNumber": "+1234567890",  # same as phone_number
                "dataMessage": {"message": "self message"},
            }
        }
        await signal_gw._process_message(data)
        handler.assert_not_called()
