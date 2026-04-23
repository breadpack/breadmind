from unittest.mock import AsyncMock

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.slack_auth import SlackAuthCheck


def _client_ok(user_id: str = "U_BOT"):
    c = AsyncMock()
    c.auth_test = AsyncMock(return_value={"ok": True, "user_id": user_id,
                                          "team": "T1", "url": "https://x/"})
    return c


def _client_err(err: str):
    c = AsyncMock()
    c.auth_test = AsyncMock(return_value={"ok": False, "error": err})
    return c


async def test_pass(monkeypatch):
    c = _client_ok("U_BOT_1")
    chk = SlackAuthCheck(token="xoxb-fake", client_factory=lambda t: c)
    out = await chk.run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.PASS
    assert "U_BOT_1" in out.detail
    assert chk.bot_user_id == "U_BOT_1"


async def test_fail_on_ok_false():
    c = _client_err("invalid_auth")
    chk = SlackAuthCheck(token="xoxb-fake", client_factory=lambda t: c)
    out = await chk.run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "invalid_auth" in out.detail


async def test_masks_token_in_detail_on_exception():
    def boom(_t):
        raise RuntimeError("token xoxb-123-SECRET-DEADBEEF leaked")

    chk = SlackAuthCheck(token="xoxb-123-SECRET-DEADBEEF", client_factory=boom)
    out = await chk.run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "SECRET-DEADBEEF" not in out.detail
    assert "xoxb-REDACTED" in out.detail
