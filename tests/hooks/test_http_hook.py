from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.http_hook import HttpHook


def _make_mock_session(status: int, json_body: dict | None = None):
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_body or {})

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=mock_ctx)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return mock_session


def _payload(event=HookEvent.PRE_TOOL_USE, data=None):
    return HookPayload(event=event, data=data or {})


async def test_proceed_on_success():
    hook = HttpHook(
        name="test-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/webhook",
    )
    mock_session = _make_mock_session(200, {"action": "proceed"})

    with patch("aiohttp.ClientSession", return_value=mock_session):
        decision = await hook.run(_payload())

    assert decision.kind.value == "proceed"
    assert decision.hook_id == "test-hook"


async def test_block_on_response():
    hook = HttpHook(
        name="block-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/webhook",
    )
    mock_session = _make_mock_session(200, {"action": "block", "reason": "denied"})

    with patch("aiohttp.ClientSession", return_value=mock_session):
        decision = await hook.run(_payload())

    assert decision.kind.value == "block"
    assert decision.reason == "denied"
    assert decision.hook_id == "block-hook"


async def test_non_2xx_failure():
    hook = HttpHook(
        name="fail-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/webhook",
    )
    mock_session = _make_mock_session(500)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        decision = await hook.run(_payload())

    # PRE_TOOL_USE is blockable → _failure_decision returns BLOCK
    assert decision.kind.value == "block"
    assert decision.hook_id == "fail-hook"


async def test_non_2xx_observational_returns_proceed():
    hook = HttpHook(
        name="obs-hook",
        event=HookEvent.SESSION_START,
        url="https://example.com/webhook",
    )
    mock_session = _make_mock_session(500)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        decision = await hook.run(_payload(event=HookEvent.SESSION_START))

    # SESSION_START is not blockable → _failure_decision returns PROCEED
    assert decision.kind.value == "proceed"


async def test_ssrf_blocked():
    hook = HttpHook(
        name="ssrf-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="http://127.0.0.1/steal",
    )

    with patch("aiohttp.ClientSession") as mock_cls:
        decision = await hook.run(_payload())
        # No HTTP call should be made
        mock_cls.assert_not_called()

    assert decision.kind.value == "block"
    assert decision.hook_id == "ssrf-hook"


async def test_env_var_interpolation(monkeypatch):
    monkeypatch.setenv("TEST_HOOK_SECRET", "supersecret")

    hook = HttpHook(
        name="env-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/$TEST_HOOK_SECRET/webhook",
        headers={"Authorization": "Bearer ${TEST_HOOK_SECRET}"},
    )

    url, headers = hook._interpolate_env()
    assert url == "https://example.com/supersecret/webhook"
    assert headers["Authorization"] == "Bearer supersecret"


async def test_if_condition_field():
    hook = HttpHook(
        name="cond-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/webhook",
        if_condition=["tool_name == 'bash'", "args.cmd != ''"],
    )
    assert hook.if_condition == ["tool_name == 'bash'", "args.cmd != ''"]


async def test_timeout_returns_failure():
    import asyncio

    hook = HttpHook(
        name="timeout-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/webhook",
        timeout_sec=0.01,
    )

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = MagicMock(return_value=mock_ctx)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        decision = await hook.run(_payload())

    assert decision.kind.value == "block"
    assert decision.hook_id == "timeout-hook"


async def test_put_method_used():
    hook = HttpHook(
        name="put-hook",
        event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/webhook",
        method="PUT",
    )
    mock_session = _make_mock_session(200, {"action": "proceed"})

    with patch("aiohttp.ClientSession", return_value=mock_session):
        await hook.run(_payload())

    mock_session.request.assert_called_once()
    call_args = mock_session.request.call_args
    assert call_args[0][0] == "PUT"
