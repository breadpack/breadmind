import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.messenger.teams_gw import TeamsGateway


class TestTeamsGateway:
    @pytest.fixture
    def gw(self):
        return TeamsGateway(app_id="test_app_id", app_password="test_password")

    @pytest.mark.asyncio
    async def test_start(self, gw):
        """start() authenticates and sets _connected = True."""
        with patch.object(gw, "_authenticate", new_callable=AsyncMock) as mock_auth:
            await gw.start()
            mock_auth.assert_called_once()
            assert gw._connected is True

    @pytest.mark.asyncio
    async def test_send(self, gw):
        """send() posts a message to the Bot Framework REST API."""
        gw._access_token = "fake_token"
        gw._service_url = "https://smba.trafficmanager.net/teams"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await gw.send("conv123", "Hello Teams!")

        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert "conv123" in call_args[0][0]
        assert call_args[1]["json"]["text"] == "Hello Teams!"

    @pytest.mark.asyncio
    async def test_handle_incoming(self, gw):
        """handle_incoming() dispatches message activities to the on_message callback."""
        handler = AsyncMock(return_value="bot reply")
        gw._on_message = handler

        activity = {
            "type": "message",
            "text": "hello bot",
            "from": {"id": "user1"},
            "conversation": {"id": "conv1"},
            "serviceUrl": "https://smba.trafficmanager.net/teams",
        }

        result = await gw.handle_incoming(activity)
        assert result == "bot reply"
        handler.assert_called_once()
        msg = handler.call_args[0][0]
        assert msg.text == "hello bot"
        assert msg.user_id == "user1"
        assert msg.channel_id == "conv1"
        assert msg.platform == "teams"
        assert gw._service_url == "https://smba.trafficmanager.net/teams"

    @pytest.mark.asyncio
    async def test_ask_approval(self, gw):
        """ask_approval() sends an approval message and returns an action_id."""
        with patch.object(gw, "send", new_callable=AsyncMock) as mock_send:
            action_id = await gw.ask_approval("conv1", "deploy", {"env": "prod"})
            assert len(action_id) == 8
            mock_send.assert_called_once()
            sent_text = mock_send.call_args[0][1]
            assert "deploy" in sent_text
            assert action_id in sent_text

    @pytest.mark.asyncio
    async def test_handle_non_message_activity(self, gw):
        """handle_incoming() ignores non-message activities."""
        handler = AsyncMock()
        gw._on_message = handler

        result = await gw.handle_incoming({"type": "conversationUpdate"})
        assert result is None
        handler.assert_not_called()

        result = await gw.handle_incoming({"type": "message", "text": ""})
        assert result is None
        handler.assert_not_called()
