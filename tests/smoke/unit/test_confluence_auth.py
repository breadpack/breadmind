import httpx
import respx

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.confluence_auth import ConfluenceAuthCheck
from breadmind.smoke.targets import (
    AnthropicTargets, AzureTargets, ConfluenceTargets,
    LlmTargets, PilotTargets, SlackTargets,
)


def _t() -> PilotTargets:
    return PilotTargets(
        migration_head="h",
        slack=SlackTargets(required_channels=[], required_events=[]),
        confluence=ConfluenceTargets(
            base_url="https://x.atlassian.net/wiki",
            required_spaces=[],
        ),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=[]),
            azure=AzureTargets(endpoint_env="AZURE_OPENAI_ENDPOINT",
                               required_deployments=[]),
            no_training_confirmed=True,
        ),
    )


@respx.mock
async def test_auth_pass():
    respx.get("https://x.atlassian.net/wiki/rest/api/user/current").mock(
        return_value=httpx.Response(200, json={"email": "bot@c.com",
                                               "accountId": "a1"}),
    )
    out = await ConfluenceAuthCheck(
        email="bot@c.com", api_token="ATATT_stub_token_1234567890abcdef",
    ).run(_t(), timeout=5.0)
    assert out.status is CheckStatus.PASS


@respx.mock
async def test_auth_fail_401():
    respx.get("https://x.atlassian.net/wiki/rest/api/user/current").mock(
        return_value=httpx.Response(401),
    )
    out = await ConfluenceAuthCheck(
        email="bot@c.com", api_token="ATATT_stub_token_1234567890abcdef",
    ).run(_t(), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "401" in out.detail


@respx.mock
async def test_auth_fail_masks_token_in_body_leak():
    respx.get("https://x.atlassian.net/wiki/rest/api/user/current").mock(
        return_value=httpx.Response(
            403, text='leaked: ATATT_stub_token_1234567890abcdef',
        ),
    )
    out = await ConfluenceAuthCheck(
        email="bot@c.com", api_token="ATATT_stub_token_1234567890abcdef",
    ).run(_t(), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "ATATT_stub_token_1234567890abcdef" not in out.detail


@respx.mock
async def test_auth_timeout_yields_clean_detail():
    respx.get("https://x.atlassian.net/wiki/rest/api/user/current").mock(
        side_effect=httpx.ReadTimeout("slow"),
    )
    out = await ConfluenceAuthCheck(
        email="bot@c.com", api_token="ATATT_stub_token_1234567890abcdef",
    ).run(_t(), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert out.detail == "timeout"


@respx.mock
async def test_auth_200_non_json_body_fails():
    respx.get("https://x.atlassian.net/wiki/rest/api/user/current").mock(
        return_value=httpx.Response(200, text="<html>maintenance</html>"),
    )
    out = await ConfluenceAuthCheck(
        email="bot@c.com", api_token="ATATT_stub_token_1234567890abcdef",
    ).run(_t(), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "not JSON" in out.detail or "not json" in out.detail.lower()


@respx.mock
async def test_auth_200_list_body_passes_with_empty_account():
    respx.get("https://x.atlassian.net/wiki/rest/api/user/current").mock(
        return_value=httpx.Response(200, json=["unexpected", "list"]),
    )
    out = await ConfluenceAuthCheck(
        email="bot@c.com", api_token="ATATT_stub_token_1234567890abcdef",
    ).run(_t(), timeout=5.0)
    assert out.status is CheckStatus.PASS
    assert out.detail == "account="
