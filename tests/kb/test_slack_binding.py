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


async def test_feedback_handler_writes_audit(monkeypatch):
    calls: list = []

    async def fake_audit(**kwargs):
        calls.append(kwargs)

    import breadmind.kb.slack_binding as sb
    monkeypatch.setattr(sb, "audit_log", fake_audit)

    handler = sb.build_slack_feedback_handler()
    await handler("upvote", "answer123", "U_ALICE")
    await handler("downvote", "answer123", "U_BOB")
    await handler("bookmark", "answer123", "U_CAROL")
    kinds = [c["action"] for c in calls]
    assert "feedback_upvote" in kinds
    assert "feedback_downvote" in kinds
    assert "feedback_bookmark" in kinds


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
