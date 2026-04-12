import pytest
from breadmind.hooks.db_store import HookOverride
from breadmind.hooks.events import HookEvent
from breadmind.hooks.registry import HookRegistry


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows
    async def list_all(self):
        return list(self._rows)
    async def list_by_event(self, event):
        return [r for r in self._rows if r.event == event]
    async def insert(self, ov):
        self._rows.append(ov)
    async def delete(self, hook_id):
        self._rows = [r for r in self._rows if r.hook_id != hook_id]


async def test_build_prompt_hook_from_db():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(hook_id="llm-guard", source="user", event="pre_tool_use",
                     type="prompt", tool_pattern=None, priority=50, enabled=True,
                     config_json={"prompt": "Is this safe?", "model": "gemini-2.5-flash"}),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 1
    assert chain.handlers[0].__class__.__name__ == "PromptHook"


async def test_build_http_hook_from_db():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(hook_id="webhook", source="user", event="pre_tool_use",
                     type="http", tool_pattern=None, priority=30, enabled=True,
                     config_json={"url": "https://example.com/hook", "headers": {"X-Key": "val"}}),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 1
    assert chain.handlers[0].__class__.__name__ == "HttpHook"


async def test_build_agent_hook_from_db():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(hook_id="agent-check", source="user", event="pre_tool_use",
                     type="agent", tool_pattern=None, priority=20, enabled=True,
                     config_json={"prompt": "Verify safety", "max_turns": 2, "allowed_tools": "readonly"}),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 1
    h = chain.handlers[0]
    assert h.__class__.__name__ == "AgentHook"
    assert h.max_turns == 2


async def test_unknown_type_still_skipped():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(hook_id="bad", source="user", event="pre_tool_use",
                     type="unknown_type", tool_pattern=None, priority=0, enabled=True,
                     config_json={}),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 0
