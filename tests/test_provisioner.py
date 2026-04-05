# tests/test_provisioner.py
import pytest
from unittest.mock import AsyncMock, patch
from breadmind.provisioning.provisioner import Provisioner, DeploymentTarget, register_strategy
from breadmind.provisioning.strategies.base import DeployStrategy


def test_unknown_access_method_raises():
    p = Provisioner()
    target = DeploymentTarget(
        host="some-host",
        access_method="nonexistent",
        environment={},
    )
    with pytest.raises(ValueError, match="Unknown access method"):
        p.select_strategy(target)


def test_register_and_select_strategy():
    """Registered strategies can be resolved by select_strategy."""
    register_strategy("test_dummy", "tests.test_provisioner._DummyStrategy")
    try:
        p = Provisioner()
        target = DeploymentTarget(host="h1", access_method="test_dummy", environment={})
        strategy = p.select_strategy(target)
        assert isinstance(strategy, DeployStrategy)
    finally:
        from breadmind.provisioning.provisioner import _STRATEGY_REGISTRY
        _STRATEGY_REGISTRY.pop("test_dummy", None)


class _DummyStrategy(DeployStrategy):
    async def deploy(self, **kwargs):
        return {"status": "ok"}

    async def remove(self, **kwargs):
        return {"status": "removed"}

    async def update(self, **kwargs):
        return {"status": "updated"}


@pytest.mark.asyncio
async def test_provision_calls_strategy_deploy():
    p = Provisioner()
    target = DeploymentTarget(host="h1", access_method="ssh", environment={})
    mock_strategy = AsyncMock(spec=DeployStrategy)
    mock_strategy.deploy = AsyncMock(return_value={"status": "ok"})
    with patch.object(p, "select_strategy", return_value=mock_strategy):
        await p.provision(target, commander_url="wss://cmd:8081", cert_data=b"cert", key_data=b"key")
    mock_strategy.deploy.assert_called_once()
