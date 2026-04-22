import httpx
import respx

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.confluence_spaces import ConfluenceSpacesCheck
from breadmind.smoke.targets import (
    AnthropicTargets,
    AzureTargets,
    ConfluenceTargets,
    LlmTargets,
    PilotTargets,
    SlackTargets,
)


def _t(spaces: list[str]) -> PilotTargets:
    return PilotTargets(
        migration_head="h",
        slack=SlackTargets(required_channels=[], required_events=[]),
        confluence=ConfluenceTargets(
            base_url="https://x.atlassian.net/wiki",
            required_spaces=spaces,
        ),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=[]),
            azure=AzureTargets(
                endpoint_env="AZURE_OPENAI_ENDPOINT",
                required_deployments=[],
            ),
            no_training_confirmed=True,
        ),
    )


@respx.mock
async def test_all_spaces_pass():
    respx.get("https://x.atlassian.net/wiki/rest/api/space/ENG").mock(
        return_value=httpx.Response(200, json={"key": "ENG"}),
    )
    respx.get("https://x.atlassian.net/wiki/rest/api/space/ONBOARD").mock(
        return_value=httpx.Response(200, json={"key": "ONBOARD"}),
    )
    out = await ConfluenceSpacesCheck(email="e", api_token="ATATT_abc_1234567890").run(
        _t(["ENG", "ONBOARD"]), timeout=5.0,
    )
    assert out.status is CheckStatus.PASS


@respx.mock
async def test_403_reports_permission():
    respx.get("https://x.atlassian.net/wiki/rest/api/space/SEC").mock(
        return_value=httpx.Response(403, text="forbidden"),
    )
    out = await ConfluenceSpacesCheck(email="e", api_token="ATATT_abc_1234567890").run(
        _t(["SEC"]), timeout=5.0,
    )
    assert out.status is CheckStatus.FAIL
    assert "SEC" in out.detail
    assert "403" in out.detail


@respx.mock
async def test_404_reports_missing():
    respx.get("https://x.atlassian.net/wiki/rest/api/space/NOPE").mock(
        return_value=httpx.Response(404),
    )
    out = await ConfluenceSpacesCheck(email="e", api_token="ATATT_abc_1234567890").run(
        _t(["NOPE"]), timeout=5.0,
    )
    assert out.status is CheckStatus.FAIL
    assert "NOPE" in out.detail
    assert "404" in out.detail


async def test_empty_spaces_pass():
    out = await ConfluenceSpacesCheck(email="e", api_token="t").run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.PASS
