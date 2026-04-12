from breadmind.hooks import HookDecision, DecisionKind


def test_proceed_default():
    d = HookDecision.proceed()
    assert d.kind is DecisionKind.PROCEED
    assert d.patch == {}
    assert d.reply is None
    assert d.reroute_target is None


def test_block_carries_reason():
    d = HookDecision.block("forbidden")
    assert d.kind is DecisionKind.BLOCK
    assert d.reason == "forbidden"


def test_modify_captures_patch():
    d = HookDecision.modify(args={"cmd": "safe"}, note="sanitized")
    assert d.kind is DecisionKind.MODIFY
    assert d.patch == {"args": {"cmd": "safe"}, "note": "sanitized"}


def test_reply_stores_result():
    d = HookDecision.reply("cached", context="from-cache")
    assert d.kind is DecisionKind.REPLY
    assert d.reply == "cached"
    assert d.context == "from-cache"


def test_reroute_stores_target_and_args():
    d = HookDecision.reroute("k8s_exec", namespace="prod")
    assert d.kind is DecisionKind.REROUTE
    assert d.reroute_target == "k8s_exec"
    assert d.reroute_args == {"namespace": "prod"}
