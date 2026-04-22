from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.declarative import NoTrainingCheck
from breadmind.smoke.targets import (
    AnthropicTargets, AzureTargets, ConfluenceTargets,
    LlmTargets, PilotTargets, SlackTargets,
)


def _t(confirmed: bool) -> PilotTargets:
    return PilotTargets(
        migration_head="h",
        slack=SlackTargets(required_channels=[], required_events=[]),
        confluence=ConfluenceTargets(base_url="https://x/wiki", required_spaces=[]),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=[]),
            azure=AzureTargets(endpoint_env="AZURE_OPENAI_ENDPOINT",
                               required_deployments=[]),
            no_training_confirmed=confirmed,
        ),
    )


async def test_pass_when_confirmed():
    out = await NoTrainingCheck().run(_t(True), timeout=5.0)
    assert out.status is CheckStatus.PASS


async def test_fail_when_not_confirmed():
    out = await NoTrainingCheck().run(_t(False), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "no_training_confirmed" in out.detail
