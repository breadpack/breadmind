import httpx
import respx

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.anthropic import AnthropicCheck
from breadmind.smoke.targets import (
    AnthropicTargets, AzureTargets, ConfluenceTargets,
    LlmTargets, PilotTargets, SlackTargets,
)


def _t(models: list[str]) -> PilotTargets:
    return PilotTargets(
        migration_head="h",
        slack=SlackTargets(required_channels=[], required_events=[]),
        confluence=ConfluenceTargets(base_url="https://x/wiki", required_spaces=[]),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=models),
            azure=AzureTargets(endpoint_env="AZURE_OPENAI_ENDPOINT",
                               required_deployments=[]),
            no_training_confirmed=True,
        ),
    )


@respx.mock
async def test_pass_when_all_models_present(monkeypatch):
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "claude-sonnet-4-6"},
            {"id": "claude-opus-4-7"},
            {"id": "claude-haiku-4-5-20251001"},
        ]}),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub-1234567890")
    out = await AnthropicCheck().run(
        _t(["claude-sonnet-4-6", "claude-opus-4-7"]), timeout=5.0,
    )
    assert out.status is CheckStatus.PASS


@respx.mock
async def test_fail_missing_model(monkeypatch):
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "claude-sonnet-4-6"}]}),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub-1234567890")
    out = await AnthropicCheck().run(
        _t(["claude-sonnet-4-6", "claude-opus-4-7"]), timeout=5.0,
    )
    assert out.status is CheckStatus.FAIL
    assert "claude-opus-4-7" in out.detail


async def test_fail_missing_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = await AnthropicCheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "ANTHROPIC_API_KEY" in out.detail


@respx.mock
async def test_fail_on_401(monkeypatch):
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(401),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub-1234567890")
    out = await AnthropicCheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "401" in out.detail


# PROACTIVE - regression lock for httpx timeout (not asyncio.TimeoutError)
@respx.mock
async def test_timeout_yields_clean_detail(monkeypatch):
    respx.get("https://api.anthropic.com/v1/models").mock(
        side_effect=httpx.ReadTimeout("slow"),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub-1234567890")
    out = await AnthropicCheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert out.detail == "timeout"


# PROACTIVE - regression lock for non-JSON 200 body
@respx.mock
async def test_200_non_json_body_fails(monkeypatch):
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, text="<html>maintenance</html>"),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-stub-1234567890")
    out = await AnthropicCheck().run(_t([]), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "not JSON" in out.detail or "not json" in out.detail.lower()
