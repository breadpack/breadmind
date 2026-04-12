import pytest

from breadmind.core.events import EventBus
from breadmind.hooks import HookDecision, HookEvent
from breadmind.hooks.handler import PythonHook


class _FakeProvider:
    name = "fake"

    async def _chat_impl(self, messages, **kwargs):
        return {"text": "hello " + messages[-1]["content"]}


@pytest.fixture
def fresh_global_bus(monkeypatch):
    import breadmind.core.events as ev
    monkeypatch.setattr(ev, "_bus", EventBus())
    return ev._bus


async def test_llm_request_can_block(fresh_global_bus):
    from breadmind.llm.base import chat_with_hooks

    fresh_global_bus.register_hook(
        HookEvent.LLM_REQUEST,
        PythonHook(
            name="deny",
            event=HookEvent.LLM_REQUEST,
            handler=lambda p: HookDecision.block("no llm today"),
        ),
    )

    provider = _FakeProvider()
    with pytest.raises(PermissionError, match="no llm today"):
        await chat_with_hooks(
            provider,
            provider._chat_impl,
            messages=[{"role": "user", "content": "hi"}],
        )


async def test_llm_response_can_mutate(fresh_global_bus):
    from breadmind.llm.base import chat_with_hooks

    def mutate(p):
        return HookDecision.modify(text="[CENSORED]")

    fresh_global_bus.register_hook(
        HookEvent.LLM_RESPONSE,
        PythonHook(name="mask", event=HookEvent.LLM_RESPONSE, handler=mutate),
    )

    provider = _FakeProvider()
    result = await chat_with_hooks(
        provider,
        provider._chat_impl,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result["text"] == "[CENSORED]"
