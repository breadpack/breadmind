# tests/kb/test_slack_binding.py
from unittest.mock import AsyncMock, MagicMock

from breadmind.kb.slack_binding import build_slack_query_handler
from breadmind.messenger.router import IncomingMessage, OutgoingMessage


async def test_handler_invokes_pipeline_and_returns_text():
    pipeline = MagicMock()
    pipeline.answer = AsyncMock(return_value=OutgoingMessage(
        text="answer body", channel_id="C1", platform="slack",
    ))
    handler = build_slack_query_handler(pipeline)
    inc = IncomingMessage(
        text="q", user_id="U_ALICE", channel_id="C1", platform="slack",
    )
    out = await handler(inc)
    assert out == "answer body"
    pipeline.answer.assert_awaited_once_with(inc)


async def test_handler_skips_approval_messages():
    pipeline = MagicMock()
    pipeline.answer = AsyncMock()
    handler = build_slack_query_handler(pipeline)
    inc = IncomingMessage(
        text="approve xyz", user_id="U_ALICE", channel_id="C1", platform="slack",
        is_approval=True,
    )
    out = await handler(inc)
    assert out is None
    pipeline.answer.assert_not_awaited()
