"""Abstract deployment strategy interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class DeployStrategy(ABC):
    @abstractmethod
    async def deploy(
        self,
        host: str,
        commander_url: str,
        cert_data: bytes,
        key_data: bytes,
        config: dict | None = None,
    ) -> dict[str, Any]:
        """Deploy worker to target. Returns deployment result."""
        ...

    @abstractmethod
    async def remove(self, host: str) -> dict[str, Any]:
        """Remove worker from target."""
        ...

    @abstractmethod
    async def update(self, host: str, package_data: bytes, signature: bytes) -> dict[str, Any]:
        """Update worker on target."""
        ...
