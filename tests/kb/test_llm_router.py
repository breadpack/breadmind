# tests/kb/test_llm_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from breadmind.llm.base import LLMMessage, LLMResponse, TokenUsage
from breadmind.llm.router import AllProvidersFailed, LLMRouter


def _mk_provider(name: str, response: LLMResponse | None = None,
                 fail: Exception | None = None):
    p = MagicMock()
    p.model_name = name
    if fail is not None:
        p.chat = AsyncMock(side_effect=fail)
    else:
        p.chat = AsyncMock(return_value=response)
    return p


async def test_first_provider_wins():
    ok = LLMResponse(
        content="ok", tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end",
    )
    p1 = _mk_provider("a", response=ok)
    p2 = _mk_provider("b", response=ok)
    router = LLMRouter(providers=[p1, p2])
    out = await router.chat([LLMMessage(role="user", content="hi")])
    assert out.content == "ok"
    assert p1.chat.await_count == 1
    assert p2.chat.await_count == 0


async def test_cascades_to_next_on_failure():
    ok = LLMResponse(
        content="fallback-ok", tool_calls=[],
        usage=TokenUsage(input_tokens=1, output_tokens=2), stop_reason="end",
    )
    p1 = _mk_provider("a", fail=RuntimeError("boom"))
    p2 = _mk_provider("b", response=ok)
    router = LLMRouter(providers=[p1, p2])
    out = await router.chat([LLMMessage(role="user", content="hi")])
    assert out.content == "fallback-ok"
    assert len(router.metrics) == 2
    assert router.metrics[0].ok is False
    assert router.metrics[1].ok is True


async def test_all_providers_fail_raises():
    p1 = _mk_provider("a", fail=RuntimeError("x"))
    p2 = _mk_provider("b", fail=RuntimeError("y"))
    router = LLMRouter(providers=[p1, p2])
    with pytest.raises(AllProvidersFailed):
        await router.chat([LLMMessage(role="user", content="hi")])
