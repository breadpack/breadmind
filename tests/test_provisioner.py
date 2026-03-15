# tests/test_provisioner.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.provisioning.provisioner import Provisioner, DeploymentTarget
from breadmind.provisioning.strategies.base import DeployStrategy

def test_detect_kubernetes_environment():
    p = Provisioner()
    target = DeploymentTarget(
        host="k8s-node1",
        access_method="kubernetes",
        environment={"runtime": "containerd"},
    )
    strategy = p.select_strategy(target)
    assert strategy.__class__.__name__ == "KubernetesStrategy"

def test_detect_proxmox_environment():
    p = Provisioner()
    target = DeploymentTarget(
        host="pve-host1",
        access_method="proxmox",
        environment={"type": "proxmox"},
    )
    strategy = p.select_strategy(target)
    assert strategy.__class__.__name__ == "ProxmoxStrategy"

def test_detect_ssh_fallback():
    p = Provisioner()
    target = DeploymentTarget(
        host="linux-server",
        access_method="ssh",
        environment={"os": "linux"},
    )
    strategy = p.select_strategy(target)
    assert strategy.__class__.__name__ == "SSHStrategy"

@pytest.mark.asyncio
async def test_provision_calls_strategy_deploy():
    p = Provisioner()
    target = DeploymentTarget(host="h1", access_method="ssh", environment={})
    mock_strategy = AsyncMock(spec=DeployStrategy)
    mock_strategy.deploy = AsyncMock(return_value={"status": "ok"})
    with patch.object(p, "select_strategy", return_value=mock_strategy):
        result = await p.provision(target, commander_url="wss://cmd:8081", cert_data=b"cert", key_data=b"key")
    mock_strategy.deploy.assert_called_once()
