from unittest.mock import AsyncMock

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.slack_channels import SlackChannelsCheck
from breadmind.smoke.targets import (
    AnthropicTargets, AzureTargets, ConfluenceTargets,
    LlmTargets, PilotTargets, SlackTargets,
)


def _targets(channels: list[str]) -> PilotTargets:
    return PilotTargets(
        migration_head="h",
        slack=SlackTargets(required_channels=channels, required_events=[]),
        confluence=ConfluenceTargets(base_url="https://x/wiki", required_spaces=[]),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=[]),
            azure=AzureTargets(endpoint_env="AZURE_OPENAI_ENDPOINT",
                               required_deployments=[]),
            no_training_confirmed=True,
        ),
    )


def _members_client(per_channel: dict[str, list[str]]):
    c = AsyncMock()

    async def _conversations_members(channel: str, cursor: str = ""):
        members = per_channel.get(channel, [])
        return {"ok": True, "members": members,
                "response_metadata": {"next_cursor": ""}}
    c.conversations_members = AsyncMock(side_effect=_conversations_members)
    return c


async def test_pass_when_bot_member():
    c = _members_client({"C1": ["U_BOT", "U_X"], "C2": ["U_BOT"]})
    chk = SlackChannelsCheck(token="t", bot_user_id="U_BOT",
                             client_factory=lambda t: c)
    out = await chk.run(_targets(["C1", "C2"]), timeout=5.0)
    assert out.status is CheckStatus.PASS


async def test_fail_when_bot_not_member():
    c = _members_client({"C1": ["U_BOT"], "C2": ["U_OTHER"]})
    chk = SlackChannelsCheck(token="t", bot_user_id="U_BOT",
                             client_factory=lambda t: c)
    out = await chk.run(_targets(["C1", "C2"]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "C2" in out.detail
    assert "/invite" in out.detail


async def test_empty_channels_is_pass():
    c = _members_client({})
    chk = SlackChannelsCheck(token="t", bot_user_id="U_BOT",
                             client_factory=lambda t: c)
    out = await chk.run(_targets([]), timeout=5.0)
    assert out.status is CheckStatus.PASS
    assert c.conversations_members.await_count == 0
