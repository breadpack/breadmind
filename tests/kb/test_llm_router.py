# tests/kb/test_llm_router.py
from unittest.mock import AsyncMock, MagicMock

from breadmind.llm.base import LLMMessage, LLMResponse, TokenUsage
from breadmind.llm.router import AllProvidersFailed, LLMRouter  # noqa: F401


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
