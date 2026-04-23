from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.confluence_base_url import ConfluenceBaseUrlCheck
from breadmind.smoke.targets import (
    AnthropicTargets, AzureTargets, ConfluenceTargets,
    LlmTargets, PilotTargets, SlackTargets,
)


def _t(url: str) -> PilotTargets:
    return PilotTargets(
        migration_head="h",
        slack=SlackTargets(required_channels=[], required_events=[]),
        confluence=ConfluenceTargets(base_url=url, required_spaces=[]),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=[]),
            azure=AzureTargets(endpoint_env="AZURE_OPENAI_ENDPOINT",
                               required_deployments=[]),
            no_training_confirmed=True,
        ),
    )


async def test_https_passes():
    out = await ConfluenceBaseUrlCheck().run(_t("https://x.atlassian.net/wiki"), 5.0)
    assert out.status is CheckStatus.PASS


async def test_http_fails():
    out = await ConfluenceBaseUrlCheck().run(_t("http://x.atlassian.net/wiki"), 5.0)
    assert out.status is CheckStatus.FAIL
    assert "https" in out.detail.lower()


async def test_missing_scheme_fails():
    out = await ConfluenceBaseUrlCheck().run(_t("x.atlassian.net"), 5.0)
    assert out.status is CheckStatus.FAIL
