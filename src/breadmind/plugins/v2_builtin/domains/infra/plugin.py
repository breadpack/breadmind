"""인프라 도메인 플러그인."""
from __future__ import annotations
from typing import Any
from breadmind.core.v2_plugin import PluginManifest
from breadmind.plugins.v2_builtin.domains.infra.tools import ALL_INFRA_TOOLS
from breadmind.plugins.v2_builtin.domains.infra.roles import INFRA_ROLES


class InfraPlugin:
    """K8s, Proxmox, OpenWrt 인프라 도메인 플러그인."""

    manifest = PluginManifest(
        name="infra",
        version="1.0.0",
        provides=["infra_tools", "infra_roles"],
        depends_on=[],
    )

    async def setup(self, container: Any, events: Any) -> None:
        # Register tools if tool registry is available
        if container.has(type("ToolProtocol", (), {})):
            registry = container.resolve(type("ToolProtocol", (), {}))
            for tool in ALL_INFRA_TOOLS:
                registry.register(tool)

    async def teardown(self) -> None:
        pass

    @staticmethod
    def get_tools():
        return ALL_INFRA_TOOLS

    @staticmethod
    def get_roles():
        return INFRA_ROLES
