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
