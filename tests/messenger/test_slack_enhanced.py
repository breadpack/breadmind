from breadmind.messenger.slack_enhanced import SlackEnhancedGateway


def test_strip_mention_prefix():
    gw = SlackEnhancedGateway(
        bot_token="x", bot_user_id="U_BOT", on_message=None,
    )
    assert gw._strip_mention("<@U_BOT> hello") == "hello"
    assert gw._strip_mention("<@U_BOT>  hello there") == "hello there"
    assert gw._strip_mention("no mention") == "no mention"
    assert gw._strip_mention("<@U_OTHER> hello") == "<@U_OTHER> hello"
