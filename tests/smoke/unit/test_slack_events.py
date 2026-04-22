from unittest.mock import AsyncMock

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.slack_events import SlackEventsCheck


def _client_ws(url: str = "wss://wss.slack/x"):
    c = AsyncMock()
    c.apps_connections_open = AsyncMock(return_value={"ok": True, "url": url})
    return c


async def test_pass_returns_ws_url():
    c = _client_ws()
    chk = SlackEventsCheck(app_token="xapp-1-T-0-a", client_factory=lambda t: c)
    out = await chk.run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.PASS
    assert "wss" in out.detail


async def test_fail_on_not_ok():
    c = AsyncMock()
    c.apps_connections_open = AsyncMock(
        return_value={"ok": False, "error": "missing_scope"},
    )
    chk = SlackEventsCheck(app_token="xapp-1", client_factory=lambda t: c)
    out = await chk.run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "missing_scope" in out.detail
