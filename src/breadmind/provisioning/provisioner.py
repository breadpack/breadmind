"""Environment detection and deployment orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from breadmind.provisioning.strategies.base import DeployStrategy

logger = logging.getLogger(__name__)


@dataclass
class DeploymentTarget:
    host: str
    access_method: str  # kubernetes | proxmox | ssh
    environment: dict[str, Any] = field(default_factory=dict)


class Provisioner:
    """Detects target environment and selects deployment strategy."""

    def select_strategy(self, target: DeploymentTarget) -> DeployStrategy:
        method = target.access_method.lower()
        if method == "kubernetes":
            from breadmind.provisioning.strategies.kubernetes import KubernetesStrategy
            return KubernetesStrategy()
        elif method == "proxmox":
            from breadmind.provisioning.strategies.proxmox import ProxmoxStrategy
            return ProxmoxStrategy()
        else:
            from breadmind.provisioning.strategies.ssh import SSHStrategy
            return SSHStrategy()

    async def provision(
        self,
        target: DeploymentTarget,
        commander_url: str,
        cert_data: bytes,
        key_data: bytes,
        config: dict | None = None,
    ) -> dict[str, Any]:
        strategy = self.select_strategy(target)
        logger.info("Deploying worker to %s via %s", target.host, type(strategy).__name__)
        return await strategy.deploy(
            host=target.host,
            commander_url=commander_url,
            cert_data=cert_data,
            key_data=key_data,
            config=config,
        )

    async def remove(self, target: DeploymentTarget) -> dict[str, Any]:
        strategy = self.select_strategy(target)
        return await strategy.remove(host=target.host)
