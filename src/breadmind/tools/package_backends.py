"""Package type backends implementing the strategy pattern.

Each backend encapsulates the operations for a specific PackageType,
eliminating if/elif chains in PackageManager.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from breadmind.tools.package_manager import Package, PackageType

logger = logging.getLogger(__name__)


class PackageBackend(ABC):
    """Strategy interface for package type operations."""

    @property
    @abstractmethod
    def package_type(self) -> PackageType: ...

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[Package]: ...

    @abstractmethod
    async def list_packages(self) -> list[Package]: ...

    @abstractmethod
    async def install(self, name: str, source: str = "") -> dict[str, Any]:
        """Install a package. Returns dict with 'success', 'message', and optional extra keys."""
        ...

    @abstractmethod
    async def uninstall(self, name: str) -> dict[str, Any]:
        """Uninstall a package. Returns dict with 'success', 'message'."""
        ...

    @abstractmethod
    async def info(self, name: str) -> Package | None: ...

    async def enable(self, name: str) -> dict[str, Any]:
        return {"success": False, "message": "Enable not supported for this package type"}

    async def disable(self, name: str) -> dict[str, Any]:
        return {"success": False, "message": "Disable not supported for this package type"}


class SkillBackend(PackageBackend):
    """Backend for skill packages."""

    def __init__(self, skill_store) -> None:
        self._store = skill_store

    @property
    def package_type(self) -> PackageType:
        return PackageType.SKILL

    async def search(self, query: str, limit: int = 10) -> list[Package]:
        try:
            skills = await self._store.find_matching_skills(query, limit=limit)
            return [
                Package(
                    name=s.name,
                    type=PackageType.SKILL,
                    description=s.description,
                    status="installed",
                    source=s.source,
                )
                for s in skills
            ]
        except Exception as e:
            logger.warning("Skill search failed: %s", e)
            return []

    async def list_packages(self) -> list[Package]:
        try:
            skills = await self._store.list_skills()
            return [
                Package(
                    name=s.name,
                    type=PackageType.SKILL,
                    description=s.description,
                    status="installed",
                    source=s.source,
                )
                for s in skills
            ]
        except Exception:
            return []

    async def install(self, name: str, source: str = "") -> dict[str, Any]:
        skill = await self._store.add_skill(
            name=name,
            description=f"Skill: {name}",
            prompt_template="",
            steps=[],
            trigger_keywords=[name],
            source=source or "package_manager",
        )
        return {
            "success": True,
            "message": f"Skill '{name}' installed successfully.",
            "package": Package(
                name=skill.name,
                type=PackageType.SKILL,
                description=skill.description,
                status="installed",
                source=skill.source,
            ),
        }

    async def uninstall(self, name: str) -> dict[str, Any]:
        removed = await self._store.remove_skill(name)
        if not removed:
            return {"success": False, "message": f"Skill '{name}' not found."}
        return {"success": True, "message": f"Skill '{name}' uninstalled."}

    async def info(self, name: str) -> Package | None:
        skill = await self._store.get_skill(name)
        if skill:
            return Package(
                name=skill.name,
                type=PackageType.SKILL,
                description=skill.description,
                status="installed",
                source=skill.source,
                metadata={
                    "usage_count": skill.usage_count,
                    "success_count": skill.success_count,
                    "trigger_keywords": skill.trigger_keywords,
                },
            )
        return None


class MCPBackend(PackageBackend):
    """Backend for MCP server packages."""

    def __init__(self, mcp_store) -> None:
        self._store = mcp_store

    @property
    def package_type(self) -> PackageType:
        return PackageType.MCP_SERVER

    async def search(self, query: str, limit: int = 10) -> list[Package]:
        try:
            results = await self._store.search(query, limit=limit)
            return [
                Package(
                    name=r.get("name", r.get("slug", "")),
                    type=PackageType.MCP_SERVER,
                    description=r.get("description", ""),
                    status="available",
                    source=r.get("source", ""),
                    metadata=r,
                )
                for r in results
            ]
        except Exception as e:
            logger.warning("MCP search failed: %s", e)
            return []

    async def list_packages(self) -> list[Package]:
        try:
            servers = await self._store.list_installed()
            return [
                Package(
                    name=s["name"],
                    type=PackageType.MCP_SERVER,
                    description="",
                    status=s.get("status", "installed"),
                    source=s.get("source", ""),
                    metadata={"tools": s.get("tools", [])},
                )
                for s in servers
            ]
        except Exception:
            return []

    async def install(self, name: str, source: str = "") -> dict[str, Any]:
        # Search for the server to get install details
        results = await self._store.search(name, limit=1)
        if not results:
            return {
                "success": False,
                "message": f"MCP server '{name}' not found in registries.",
            }
        server_meta = results[0]
        analysis = await self._store.analyze_server(server_meta)
        result = await self._store.install_server(
            name=name,
            slug=server_meta.get("slug", name),
            command=analysis.get("command", ""),
            args=analysis.get("args", []),
            source=source or server_meta.get("source", ""),
        )
        if result.get("status") == "ok":
            return {
                "success": True,
                "message": f"MCP server '{name}' installed with "
                f"{result.get('tool_count', 0)} tools.",
                "package": Package(
                    name=name,
                    type=PackageType.MCP_SERVER,
                    description=server_meta.get("description", ""),
                    status="installed",
                    source=source or server_meta.get("source", ""),
                    metadata=result,
                ),
                "details": result,
            }
        return {
            "success": False,
            "message": f"Failed to install MCP server '{name}': "
            f"{result.get('error', 'unknown error')}",
            "details": result,
        }

    async def uninstall(self, name: str) -> dict[str, Any]:
        result = await self._store.remove_server(name)
        if result.get("status") != "ok":
            return {
                "success": False,
                "message": f"Failed to remove MCP server '{name}': "
                f"{result.get('error', '')}",
            }
        return {"success": True, "message": f"Mcp_server '{name}' uninstalled."}

    async def info(self, name: str) -> Package | None:
        # MCP doesn't have a direct get-by-name; rely on list
        try:
            servers = await self._store.list_installed()
            for s in servers:
                if s["name"] == name:
                    return Package(
                        name=s["name"],
                        type=PackageType.MCP_SERVER,
                        description="",
                        status=s.get("status", "installed"),
                        source=s.get("source", ""),
                        metadata=s,
                    )
        except Exception:
            pass
        return None


class PluginBackend(PackageBackend):
    """Backend for plugin packages."""

    def __init__(self, plugin_manager) -> None:
        self._mgr = plugin_manager

    @property
    def package_type(self) -> PackageType:
        return PackageType.PLUGIN

    async def search(self, query: str, limit: int = 10) -> list[Package]:
        try:
            manifests = await self._mgr.discover()
            query_lower = query.lower()
            results = []
            for m in manifests:
                if query_lower in m.name.lower() or query_lower in m.description.lower():
                    loaded = m.name in self._mgr.loaded_plugins
                    results.append(
                        Package(
                            name=m.name,
                            type=PackageType.PLUGIN,
                            version=m.version,
                            description=m.description,
                            status="enabled" if loaded else "disabled",
                            source="local",
                        )
                    )
            return results
        except Exception as e:
            logger.warning("Plugin search failed: %s", e)
            return []

    async def list_packages(self) -> list[Package]:
        try:
            manifests = await self._mgr.discover()
            loaded = self._mgr.loaded_plugins
            return [
                Package(
                    name=m.name,
                    type=PackageType.PLUGIN,
                    version=m.version,
                    description=m.description,
                    status="enabled" if m.name in loaded else "disabled",
                    source="local",
                )
                for m in manifests
            ]
        except Exception:
            return []

    async def install(self, name: str, source: str = "") -> dict[str, Any]:
        install_source = source or name
        manifest = await self._mgr.install(install_source)
        return {
            "success": True,
            "message": f"Plugin '{manifest.name}' v{manifest.version} installed.",
            "package": Package(
                name=manifest.name,
                type=PackageType.PLUGIN,
                version=manifest.version,
                description=manifest.description,
                status="installed",
                source=source or "local",
            ),
        }

    async def uninstall(self, name: str) -> dict[str, Any]:
        await self._mgr.uninstall(name)
        return {"success": True, "message": f"Plugin '{name}' uninstalled."}

    async def info(self, name: str) -> Package | None:
        manifest = self._mgr.get_manifest(name)
        if manifest:
            loaded = name in self._mgr.loaded_plugins
            return Package(
                name=manifest.name,
                type=PackageType.PLUGIN,
                version=manifest.version,
                description=manifest.description,
                status="enabled" if loaded else "disabled",
                source="local",
            )
        return None

    async def enable(self, name: str) -> dict[str, Any]:
        result = await self._mgr.load(name)
        if result is None:
            return {
                "success": False,
                "message": f"Plugin '{name}' not found or failed to load.",
            }
        return {"success": True, "message": f"Plugin '{name}' enabled."}

    async def disable(self, name: str) -> dict[str, Any]:
        await self._mgr.unload(name)
        return {"success": True, "message": f"Plugin '{name}' disabled."}


class ToolBackend(PackageBackend):
    """Backend for tool packages."""

    def __init__(self, tool_registry) -> None:
        self._registry = tool_registry

    @property
    def package_type(self) -> PackageType:
        return PackageType.TOOL

    async def search(self, query: str, limit: int = 10) -> list[Package]:
        try:
            definitions = self._registry.get_all_definitions()
            query_lower = query.lower()
            results = []
            for d in definitions:
                if query_lower in d.name.lower() or query_lower in d.description.lower():
                    source = self._registry.get_tool_source(d.name)
                    results.append(
                        Package(
                            name=d.name,
                            type=PackageType.TOOL,
                            description=d.description,
                            status="enabled",
                            source=source,
                        )
                    )
            return results
        except Exception as e:
            logger.warning("Tool search failed: %s", e)
            return []

    async def list_packages(self) -> list[Package]:
        try:
            definitions = self._registry.get_all_definitions()
            return [
                Package(
                    name=d.name,
                    type=PackageType.TOOL,
                    description=d.description,
                    status="enabled",
                    source=self._registry.get_tool_source(d.name),
                )
                for d in definitions
            ]
        except Exception:
            return []

    async def install(self, name: str, source: str = "") -> dict[str, Any]:
        return {
            "success": False,
            "message": f"Install not supported for type 'tool'.",
        }

    async def uninstall(self, name: str) -> dict[str, Any]:
        removed = self._registry.unregister(name)
        if not removed:
            return {"success": False, "message": f"Tool '{name}' not found."}
        return {"success": True, "message": f"Tool '{name}' uninstalled."}

    async def info(self, name: str) -> Package | None:
        if self._registry.has_tool(name):
            definitions = self._registry.get_all_definitions()
            for d in definitions:
                if d.name == name:
                    return Package(
                        name=d.name,
                        type=PackageType.TOOL,
                        description=d.description,
                        status="enabled",
                        source=self._registry.get_tool_source(name),
                    )
        return None
