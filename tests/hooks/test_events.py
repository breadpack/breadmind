from breadmind.hooks.events import (
    HookEvent,
    HookPayload,
    EVENT_POLICY,
    is_blockable,
    is_mutable,
    allows_reply,
    allows_reroute,
)


def test_catalog_contains_claude_code_events():
    for name in ["SESSION_START", "SESSION_END", "USER_PROMPT_SUBMIT",
                 "PRE_TOOL_USE", "POST_TOOL_USE", "STOP",
                 "SUBAGENT_STOP", "NOTIFICATION", "PRE_COMPACT"]:
        assert hasattr(HookEvent, name)


def test_catalog_contains_breadmind_events():
    for name in ["MESSENGER_RECEIVED", "MESSENGER_SENDING",
                 "SAFETY_GUARD_TRIGGERED", "WORKER_DISPATCHED",
                 "WORKER_COMPLETED", "LLM_REQUEST", "LLM_RESPONSE",
                 "MEMORY_WRITTEN", "PLUGIN_LOADED", "PLUGIN_UNLOADED",
                 "CREDENTIAL_ACCESSED"]:
        assert hasattr(HookEvent, name)


def test_pre_tool_use_is_blockable_and_mutable_and_reroutable():
    assert is_blockable(HookEvent.PRE_TOOL_USE)
    assert is_mutable(HookEvent.PRE_TOOL_USE)
    assert allows_reply(HookEvent.PRE_TOOL_USE)
    assert allows_reroute(HookEvent.PRE_TOOL_USE)


def test_session_start_is_observational():
    assert not is_blockable(HookEvent.SESSION_START)
    assert not is_mutable(HookEvent.SESSION_START)
    assert not allows_reply(HookEvent.SESSION_START)
    assert not allows_reroute(HookEvent.SESSION_START)


def test_llm_request_allows_mutation_but_not_reroute():
    assert is_blockable(HookEvent.LLM_REQUEST)
    assert is_mutable(HookEvent.LLM_REQUEST)
    assert not allows_reroute(HookEvent.LLM_REQUEST)


def test_payload_round_trip():
    p = HookPayload(
        event=HookEvent.PRE_TOOL_USE,
        data={"tool_name": "shell_exec", "args": {"cmd": "ls"}},
    )
    assert p.event == HookEvent.PRE_TOOL_USE
    assert p.data["tool_name"] == "shell_exec"
    assert p.depth == 0
    assert p.visited == set()
