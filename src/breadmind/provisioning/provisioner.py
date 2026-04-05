"""Environment detection and deployment orchestration."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

from breadmind.provisioning.strategies.base import DeployStrategy

logger = logging.getLogger(__name__)

_STRATEGY_REGISTRY: dict[str, str] = {}


def register_strategy(name: str, class_path: str) -> None:
    """Register a new provisioning strategy (or override an existing one).

    Args:
        name: Strategy key used in ``DeploymentTarget.access_method``.
        class_path: Fully-qualified ``module.ClassName`` string.
    """
    _STRATEGY_REGISTRY[name.lower()] = class_path


@dataclass
class DeploymentTarget:
    host: str
    access_method: str  # kubernetes | proxmox | ssh
    environment: dict[str, Any] = field(default_factory=dict)


class Provisioner:
    """Detects target environment and selects deployment strategy."""

    def select_strategy(self, target: DeploymentTarget) -> DeployStrategy:
        method = target.access_method.lower()
        class_path = _STRATEGY_REGISTRY.get(method)
        if not class_path:
            raise ValueError(
                f"Unknown access method {method!r}. "
                f"Register a strategy first via register_strategy()."
            )

        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls()

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
