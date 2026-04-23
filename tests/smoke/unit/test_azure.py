import httpx
import respx

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.azure import AzureOpenAICheck
from breadmind.smoke.targets import (
    AnthropicTargets, AzureTargets, ConfluenceTargets,
    LlmTargets, PilotTargets, SlackTargets,
)


def _t(deployments: list[str]) -> PilotTargets:
    return PilotTargets(
        migration_head="h",
        slack=SlackTargets(required_channels=[], required_events=[]),
        confluence=ConfluenceTargets(base_url="https://x/wiki", required_spaces=[]),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=[]),
            azure=AzureTargets(endpoint_env="AZURE_OPENAI_ENDPOINT",
                               required_deployments=deployments),
            no_training_confirmed=True,
        ),
    )


@respx.mock
async def test_pass(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://acme.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "stub-key")
    respx.get(
        "https://acme.openai.azure.com/openai/deployments",
    ).mock(return_value=httpx.Response(200, json={
        "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}],
    }))
    out = await AzureOpenAICheck().run(_t(["gpt-4o"]), timeout=5.0)
    assert out.status is CheckStatus.PASS


@respx.mock
async def test_fail_missing_deployment(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://acme.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "stub-key")
    respx.get(
        "https://acme.openai.azure.com/openai/deployments",
    ).mock(return_value=httpx.Response(200, json={"data": []}))
    out = await AzureOpenAICheck().run(_t(["gpt-4o"]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "gpt-4o" in out.detail


async def test_fail_missing_endpoint_env(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    out = await AzureOpenAICheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "AZURE_OPENAI_ENDPOINT" in out.detail


async def test_fail_missing_api_key(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://acme.openai.azure.com")
    monkeypatch.delenv("AZURE_OPENAI_KEY", raising=False)
    out = await AzureOpenAICheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "AZURE_OPENAI_KEY" in out.detail


# PROACTIVE — regression lock for httpx timeout
@respx.mock
async def test_timeout_yields_clean_detail(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://acme.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "stub-key")
    respx.get(
        "https://acme.openai.azure.com/openai/deployments",
    ).mock(side_effect=httpx.ReadTimeout("slow"))
    out = await AzureOpenAICheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert out.detail == "timeout"


# PROACTIVE — regression lock for non-JSON 200
@respx.mock
async def test_200_non_json_body_fails(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://acme.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "stub-key")
    respx.get(
        "https://acme.openai.azure.com/openai/deployments",
    ).mock(return_value=httpx.Response(200, text="<html>maintenance</html>"))
    out = await AzureOpenAICheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "not JSON" in out.detail or "not json" in out.detail.lower()
