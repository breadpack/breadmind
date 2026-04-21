from unittest.mock import AsyncMock

from breadmind.messenger.slack_enhanced import SlackEnhancedGateway


def test_strip_mention_prefix():
    gw = SlackEnhancedGateway(
        bot_token="x", bot_user_id="U_BOT", on_message=None,
    )
    assert gw._strip_mention("<@U_BOT> hello") == "hello"
    assert gw._strip_mention("<@U_BOT>  hello there") == "hello there"
    assert gw._strip_mention("no mention") == "no mention"
    assert gw._strip_mention("<@U_OTHER> hello") == "<@U_OTHER> hello"


def test_build_incoming_carries_thread_ts():
    gw = SlackEnhancedGateway(bot_token="x", bot_user_id="U_BOT", on_message=None)
    evt = {
        "text": "<@U_BOT> hello",
        "user": "U_ALICE",
        "channel": "C1",
        "ts": "1700000001.0001",
        "thread_ts": "1700000000.0000",
        "channel_type": "channel",
    }
    inc = gw._build_incoming(evt)
    assert inc.text == "hello"
    assert inc.thread_ts == "1700000000.0000"
    assert inc.is_dm is False


def test_build_incoming_dm_flag():
    gw = SlackEnhancedGateway(bot_token="x", bot_user_id="U_BOT", on_message=None)
    evt = {
        "text": "hi",
        "user": "U_ALICE",
        "channel": "D1",
        "ts": "1700000001.0001",
        "channel_type": "im",
    }
    inc = gw._build_incoming(evt)
    assert inc.is_dm is True
    assert inc.thread_ts is None


async def test_feedback_router_dispatches_upvote():
    captured: list = []

    async def handler(kind: str, answer_id: str, user_id: str):
        captured.append((kind, answer_id, user_id))

    gw = SlackEnhancedGateway(
        bot_token="x", bot_user_id="U_BOT", on_message=None, on_feedback=handler,
    )
    await gw._handle_feedback_action(
        action_id="kb_upvote_ab12cd34", user_id="U_ALICE",
    )
    assert captured == [("upvote", "ab12cd34", "U_ALICE")]


async def test_feedback_router_recognizes_all_kinds():
    kinds = []

    async def handler(kind: str, answer_id: str, user_id: str):
        kinds.append(kind)

    gw = SlackEnhancedGateway(
        bot_token="x", bot_user_id="U_BOT", on_message=None, on_feedback=handler,
    )
    await gw._handle_feedback_action("kb_upvote_a", "u")
    await gw._handle_feedback_action("kb_downvote_b", "u")
    await gw._handle_feedback_action("kb_bookmark_c", "u")
    assert kinds == ["upvote", "downvote", "bookmark"]


async def test_feedback_router_ignores_unknown():
    called = AsyncMock()
    gw = SlackEnhancedGateway(
        bot_token="x", bot_user_id="U_BOT", on_message=None, on_feedback=called,
    )
    await gw._handle_feedback_action("approve_xyz", "u")
    called.assert_not_awaited()


def test_build_answer_blocks_includes_three_action_ids():
    gw = SlackEnhancedGateway(bot_token="x", bot_user_id="U_BOT", on_message=None)
    blocks = gw.build_answer_blocks(
        body="clear cache [#1]",
        answer_id="ab12cd34",
        citations=[("confluence", "https://wiki/x")],
        confidence_badge="🟢",
    )
    flat = str(blocks)
    assert "kb_upvote_ab12cd34" in flat
    assert "kb_downvote_ab12cd34" in flat
    assert "kb_bookmark_ab12cd34" in flat
    assert "https://wiki/x" in flat
    assert "🟢" in flat


def test_format_permalink_detects_slack_archive_uri():
    gw = SlackEnhancedGateway(bot_token="x", bot_user_id="U_BOT", on_message=None)
    uri = "https://acme.slack.com/archives/C0001/p1700000001000000"
    assert gw.format_citation_link("slack_msg", uri).startswith("<" + uri)


def test_format_permalink_non_slack_passthrough():
    gw = SlackEnhancedGateway(bot_token="x", bot_user_id="U_BOT", on_message=None)
    uri = "https://wiki.acme.com/page/123"
    assert gw.format_citation_link("confluence", uri) == f"<{uri}|confluence>"
