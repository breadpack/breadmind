"""code_delegate(user, channel) propagation tests."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from breadmind.coding.tool import create_code_delegate_tool


async def test_code_delegate_long_running_forwards_user_channel(monkeypatch) -> None:
    """user/channel must reach _execute_long_running."""
    captured: dict = {}

    async def fake_execute_long_running(**kw):
        captured.update(kw)
        from breadmind.tools.registry import ToolResult
        return ToolResult(success=True, output="job started")

    monkeypatch.setattr(
        "breadmind.coding.tool._execute_long_running",
        fake_execute_long_running,
    )
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=object(),
    )
    res = await code_delegate(
        agent="claude", project="/tmp/p", prompt="hi",
        long_running=True, user="alice", channel="#dev",
    )
    assert res.success
    assert captured["user"] == "alice"
    assert captured["channel"] == "#dev"


async def test_code_delegate_default_user_channel_empty(monkeypatch) -> None:
    """Defaults are empty strings; backwards compat."""
    captured: dict = {}

    async def fake_execute_long_running(**kw):
        captured.update(kw)
        from breadmind.tools.registry import ToolResult
        return ToolResult(success=True, output="ok")

    monkeypatch.setattr(
        "breadmind.coding.tool._execute_long_running",
        fake_execute_long_running,
    )
    _, code_delegate = create_code_delegate_tool(
        db=None, session_store=AsyncMock(), provider=object(),
    )
    await code_delegate(
        agent="claude", project="/tmp/p", prompt="hi", long_running=True,
    )
    assert captured["user"] == ""
    assert captured["channel"] == ""


# Silence unused-import warning for asyncio; kept available for potential
# future spawn/cancel tests.
_ = asyncio
