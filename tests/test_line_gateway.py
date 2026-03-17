import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from breadmind.messenger.line_gw import LINEGateway


class TestLINEGateway:
    @pytest.fixture
    def line_gw(self):
        return LINEGateway(
            channel_token="test_token",
            channel_secret="test_secret",
        )

    def test_init(self, line_gw):
        assert line_gw._channel_token == "test_token"
        assert line_gw._channel_secret == "test_secret"
        assert line_gw._connected is False

    @pytest.mark.asyncio
    async def test_start_stop(self, line_gw):
        await line_gw.start()
        assert line_gw._connected is True
        await line_gw.stop()
        assert line_gw._connected is False

    @pytest.mark.asyncio
    async def test_send(self, line_gw):
        mock_resp = MagicMock()
        mock_resp.status = 200

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_ctx
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await line_gw.send("U1234", "hello")

        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        assert call_kwargs[1]["json"]["to"] == "U1234"
        assert call_kwargs[1]["json"]["messages"][0]["text"] == "hello"
        assert "Bearer test_token" in call_kwargs[1]["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_handle_webhook_text_message(self, line_gw):
        handler = AsyncMock(return_value="reply text")
        line_gw._on_message = handler
        body = {
            "events": [
                {
                    "type": "message",
                    "replyToken": "rt_abc",
                    "message": {"type": "text", "text": "hello line"},
                    "source": {"userId": "U999"},
                }
            ]
        }
        with patch.object(line_gw, "_reply", new_callable=AsyncMock) as mock_reply:
            responses = await line_gw.handle_webhook(body)

        assert responses == ["reply text"]
        handler.assert_called_once()
        msg_arg = handler.call_args[0][0]
        assert msg_arg.text == "hello line"
        assert msg_arg.platform == "line"
        assert msg_arg.user_id == "U999"
        mock_reply.assert_called_once_with("rt_abc", "reply text")

    @pytest.mark.asyncio
    async def test_handle_webhook_skips_non_text(self, line_gw):
        handler = AsyncMock()
        line_gw._on_message = handler
        body = {
            "events": [
                {
                    "type": "message",
                    "message": {"type": "image"},
                    "source": {"userId": "U999"},
                }
            ]
        }
        responses = await line_gw.handle_webhook(body)
        assert responses == [None]
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_ask_approval(self, line_gw):
        with patch.object(line_gw, "send", new_callable=AsyncMock) as mock_send:
            action_id = await line_gw.ask_approval("U1234", "deploy", {"env": "prod"})

        assert len(action_id) == 8
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "deploy" in sent_text
        assert action_id in sent_text
