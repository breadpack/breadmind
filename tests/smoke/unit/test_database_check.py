from unittest.mock import AsyncMock

import pytest

from breadmind.smoke.checks.base import CheckStatus
from breadmind.smoke.checks.database import DatabaseCheck
from breadmind.smoke.targets import (
    AnthropicTargets, AzureTargets, ConfluenceTargets,
    LlmTargets, PilotTargets, SlackTargets,
)


def _make_targets(head: str = "006_connector_configs") -> PilotTargets:
    return PilotTargets(
        migration_head=head,
        slack=SlackTargets(required_channels=[], required_events=[]),
        confluence=ConfluenceTargets(base_url="https://x/wiki", required_spaces=[]),
        llm=LlmTargets(
            anthropic=AnthropicTargets(required_models=[]),
            azure=AzureTargets(endpoint_env="AZURE_OPENAI_ENDPOINT",
                               required_deployments=[]),
            no_training_confirmed=True,
        ),
    )


async def test_pass_when_head_matches(monkeypatch):
    conn = AsyncMock()
    conn.fetchval.return_value = "006_connector_configs"
    monkeypatch.setattr(
        "breadmind.smoke.checks.database.asyncpg.connect",
        AsyncMock(return_value=conn),
    )
    monkeypatch.setenv("DATABASE_URL", "postgres://stub")
    out = await DatabaseCheck().run(_make_targets(), timeout=5.0)
    assert out.status is CheckStatus.PASS


async def test_fail_when_head_mismatches(monkeypatch):
    conn = AsyncMock()
    conn.fetchval.return_value = "004_org_kb"
    monkeypatch.setattr(
        "breadmind.smoke.checks.database.asyncpg.connect",
        AsyncMock(return_value=conn),
    )
    monkeypatch.setenv("DATABASE_URL", "postgres://stub")
    out = await DatabaseCheck().run(_make_targets("006_connector_configs"), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "004_org_kb" in out.detail
    assert "006_connector_configs" in out.detail
    assert "breadmind migrate upgrade" in out.detail


async def test_fail_when_database_url_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = await DatabaseCheck().run(_make_targets(), timeout=5.0)
    assert out.status is CheckStatus.FAIL
    assert "DATABASE_URL" in out.detail


async def test_fail_on_timeout(monkeypatch):
    async def slow(*a, **k):
        import asyncio
        await asyncio.sleep(10)

    monkeypatch.setattr(
        "breadmind.smoke.checks.database.asyncpg.connect",
        slow,
    )
    monkeypatch.setenv("DATABASE_URL", "postgres://stub")
    out = await DatabaseCheck().run(_make_targets(), timeout=0.1)
    assert out.status is CheckStatus.FAIL
    assert "timeout" in out.detail.lower()
