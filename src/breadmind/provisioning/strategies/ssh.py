"""Direct SSH installation strategy."""

from __future__ import annotations
from typing import Any
from breadmind.provisioning.strategies.base import DeployStrategy


class SSHStrategy(DeployStrategy):
    async def deploy(self, host, commander_url, cert_data, key_data, config=None) -> dict[str, Any]:
        # TODO: SSH into host, install breadmind, configure as worker
        return {"status": "deployed", "method": "ssh", "host": host}

    async def remove(self, host) -> dict[str, Any]:
        return {"status": "removed", "host": host}

    async def update(self, host, package_data, signature) -> dict[str, Any]:
        return {"status": "updated", "host": host}
