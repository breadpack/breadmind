
from breadmind.hooks import HookEvent, HookPayload
from breadmind.hooks.handler import ShellHook


async def _run(cmd: str, data=None, event=HookEvent.PRE_TOOL_USE):
    hook = ShellHook(name="t", event=event, command=cmd, shell="python")
    payload = HookPayload(event=event, data=data or {})
    return await hook.run(payload)


async def test_empty_stdout_is_proceed():
    d = await _run("pass")
    assert d.kind.value == "proceed"


async def test_block_via_json_stdout():
    cmd = (
        "import json, sys; "
        "print(json.dumps({'action':'block','reason':'forbidden'}))"
    )
    d = await _run(cmd)
    assert d.kind.value == "block"
    assert d.reason == "forbidden"


async def test_modify_via_json_stdout():
    cmd = (
        "import json, sys; "
        "print(json.dumps({'action':'modify','patch':{'args':{'cmd':'ls'}}}))"
    )
    d = await _run(cmd, data={"args": {"cmd": "rm -rf /"}})
    assert d.kind.value == "modify"
    assert d.patch == {"args": {"cmd": "ls"}}


async def test_reply_via_json_stdout():
    cmd = (
        "import json, sys; "
        "print(json.dumps({'action':'reply','result':'cached-value'}))"
    )
    d = await _run(cmd)
    assert d.kind.value == "reply"
    assert d.reply == "cached-value"


async def test_nonzero_exit_blocks_blockable_event():
    cmd = "import sys; sys.stderr.write('denied'); sys.exit(2)"
    d = await _run(cmd)
    assert d.kind.value == "block"
    assert "denied" in d.reason


async def test_nonzero_exit_on_observational_returns_proceed():
    cmd = "import sys; sys.exit(2)"
    d = await _run(cmd, event=HookEvent.SESSION_START)
    assert d.kind.value == "proceed"


async def test_stdin_payload_available():
    cmd = (
        "import json,sys; "
        "p=json.load(sys.stdin); "
        "print(json.dumps({'action':'modify','patch':{'seen':p['data']['x']}}))"
    )
    d = await _run(cmd, data={"x": 42})
    assert d.kind.value == "modify"
    assert d.patch == {"seen": 42}
