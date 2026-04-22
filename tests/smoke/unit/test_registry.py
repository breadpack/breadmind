from pathlib import Path

from breadmind.smoke.checks import build_checks


class _FakeVault:
    async def retrieve(self, cid):
        return {
            "slack_bot_token": "xoxb-stub-1234567890",
            "slack_app_token": "xapp-stub-1234567890",
            "confluence_token": "ATATT_stub_1234567890abcdef",
        }.get(cid)


def test_build_checks_order_and_names(tmp_path: Path):
    checks = build_checks(
        targets_path=tmp_path / "t.yaml",
        vault=_FakeVault(),
        confluence_email="bot@c.com",
    )
    names = [c.name for c in checks]
    assert names == [
        "config",
        "database",
        "vault",
        "slack_auth",
        "slack_channels",
        "slack_events",
        "confluence_base_url",
        "confluence_auth",
        "confluence_spaces",
        "anthropic",
        "azure_openai",
        "llm_no_training",
    ]
