import asyncio
from unittest.mock import AsyncMock

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.vault import VaultCheck


async def test_all_present():
    vault = AsyncMock()
    vault.retrieve.side_effect = lambda cid: "xxxxxxxxxx"
    out = await VaultCheck(vault=vault).run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.PASS
    assert vault.retrieve.await_count == 3


async def test_one_missing():
    vault = AsyncMock()
    vault.retrieve.side_effect = (
        lambda cid: "tok" if cid != "confluence_token" else None
    )
    out = await VaultCheck(vault=vault).run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "confluence_token" in out.detail


async def test_all_missing_lists_all():
    vault = AsyncMock()
    vault.retrieve.return_value = None
    out = await VaultCheck(vault=vault).run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.FAIL
    for cid in ("slack_bot_token", "slack_app_token", "confluence_token"):
        assert cid in out.detail


async def test_exception_redacts_secret_in_detail():
    vault = AsyncMock()
    vault.retrieve.side_effect = RuntimeError("xoxb-ABCDEFGHIJKLMNOP leaked")
    out = await VaultCheck(vault=vault).run(targets=None, timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "xoxb-ABCDEFGHIJKLMNOP" not in out.detail
    assert "slack_bot_token" in out.detail  # cid where failure happened


async def test_timeout_yields_fail():
    async def hang(cid):
        await asyncio.sleep(10)
        return "tok"
    vault = AsyncMock()
    vault.retrieve.side_effect = hang
    out = await VaultCheck(vault=vault).run(targets=None, timeout=0.01)
    assert out.status is CheckStatus.FAIL
    assert "timeout" in out.detail.lower()
