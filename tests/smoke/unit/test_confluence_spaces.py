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


@respx.mock
async def test_exception_path_no_leak():
    respx.get("https://x.atlassian.net/wiki/rest/api/space/NET").mock(
        side_effect=httpx.ConnectError("boom ATATT_stub_token_1234567890 leaked"),
    )
    out = await ConfluenceSpacesCheck(
        email="e", api_token="ATATT_stub_token_1234567890",
    ).run(_t(["NET"]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "NET" in out.detail
    assert "HTTP n/a" in out.detail
    assert "ATATT_stub_token_1234567890" not in out.detail


@respx.mock
async def test_body_secret_at_boundary_redacted():
    # Put ATATT token at position ~190-220 to force the truncation boundary.
    leaking_body = "x" * 190 + "ATATT_stub_token_AAAAAAAAAAAAAAAAAA end"
    respx.get("https://x.atlassian.net/wiki/rest/api/space/LEAK").mock(
        return_value=httpx.Response(403, text=leaking_body),
    )
    out = await ConfluenceSpacesCheck(
        email="e", api_token="ATATT_stub_token_1234567890",
    ).run(_t(["LEAK"]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "LEAK" in out.detail
    assert "403" in out.detail
    # Full token must not leak even when straddling the truncation boundary.
    assert "ATATT_stub_token_AAAAAAAAAAAAAAAAAA" not in out.detail
