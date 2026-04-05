"""Unified conversational package manager for BreadMind.

Provides a single interface for managing all package types (tools, skills,
MCP servers, plugins, search providers) through natural language.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PackageType(str, Enum):
    TOOL = "tool"
    SKILL = "skill"
    MCP_SERVER = "mcp_server"
    PLUGIN = "plugin"
    SEARCH_PROVIDER = "search_provider"


class PackageAction(str, Enum):
    SEARCH = "search"
    INSTALL = "install"
    UNINSTALL = "uninstall"
    UPDATE = "update"
    ENABLE = "enable"
    DISABLE = "disable"
    LIST = "list"
    INFO = "info"
    STATUS = "status"


@dataclass
class Package:
    name: str
    type: PackageType
    version: str = ""
    description: str = ""
    status: str = "installed"  # installed, enabled, disabled, available
    source: str = ""  # marketplace, local, builtin, mcp:server
    metadata: dict = field(default_factory=dict)


@dataclass
class PackageActionResult:
    success: bool
    action: PackageAction
    package_type: PackageType
    package_name: str
    message: str
    details: dict = field(default_factory=dict)


class IntentParser:
    """Parse natural language into package management intents.

    Examples:
    - "Install the GitHub MCP server" -> (INSTALL, MCP_SERVER, "github")
    - "Add a code review skill" -> (SEARCH, SKILL, "code review")
    - "Show me all installed plugins" -> (LIST, PLUGIN, "")
    - "Disable shell_exec" -> (DISABLE, TOOL, "shell_exec")
    - "Update all skills" -> (UPDATE, SKILL, "*")
    - "What MCP servers are running?" -> (STATUS, MCP_SERVER, "")
    - "Remove the slack plugin" -> (UNINSTALL, PLUGIN, "slack")
    - "Search for kubernetes tools" -> (SEARCH, TOOL, "kubernetes")
    """

    ACTION_PATTERNS: dict[PackageAction, list[str]] = {
        PackageAction.INSTALL: ["install", "add", "setup", "설치", "추가", "설정"],
        PackageAction.UNINSTALL: ["uninstall", "remove", "delete", "제거", "삭제"],
        PackageAction.UPDATE: ["update", "upgrade", "refresh", "업데이트", "갱신"],
        PackageAction.ENABLE: ["enable", "activate", "turn on", "활성화", "켜"],
        PackageAction.DISABLE: ["disable", "deactivate", "turn off", "비활성화", "끄"],
        PackageAction.LIST: ["list", "show", "display", "what", "목록", "보여"],
        PackageAction.SEARCH: ["search", "find", "look for", "browse", "검색", "찾"],
        PackageAction.INFO: ["info", "details", "about", "describe", "정보"],
        PackageAction.STATUS: ["status", "health", "running", "상태"],
    }

    TYPE_PATTERNS: dict[PackageType, list[str]] = {
        PackageType.TOOL: ["tool", "도구"],
        PackageType.SKILL: ["skill", "스킬"],
        PackageType.MCP_SERVER: ["mcp", "server", "서버"],
        PackageType.PLUGIN: ["plugin", "extension", "플러그인", "확장"],
        PackageType.SEARCH_PROVIDER: ["search provider", "검색 프로바이더"],
    }

    def parse(self, text: str) -> tuple[PackageAction, PackageType | None, str]:
        """Parse natural language into (action, type, query).

        Returns (action, None, query) if type can't be determined.
        """
        action = self._detect_action(text)
        pkg_type = self._detect_type(text)
        query = self._extract_query(text, action, pkg_type)
        return action, pkg_type, query

    # Actions that are more specific should win over generic ones
    # when they appear at any position.
    _SPECIFICITY: dict[PackageAction, int] = {
        PackageAction.STATUS: 10,
        PackageAction.INSTALL: 8,
        PackageAction.UNINSTALL: 8,
        PackageAction.UPDATE: 8,
        PackageAction.ENABLE: 8,
        PackageAction.DISABLE: 8,
        PackageAction.INFO: 6,
        PackageAction.SEARCH: 4,
        PackageAction.LIST: 4,
    }

    def _detect_action(self, text: str) -> PackageAction:
        lower = text.lower()
        # Collect all matching actions with their position and specificity.
        # Prefer more-specific actions; break ties by position.
        candidates: list[tuple[int, int, PackageAction]] = []
        for action, keywords in self.ACTION_PATTERNS.items():
            for kw in keywords:
                pos = lower.find(kw)
                if pos != -1:
                    spec = self._SPECIFICITY.get(action, 0)
                    # Higher specificity is better (negate for sort),
                    # lower position is better.
                    candidates.append((-spec, pos, action))
                    break  # one match per action is enough
        if not candidates:
            return PackageAction.SEARCH
        candidates.sort()
        return candidates[0][2]

    def _detect_type(self, text: str) -> PackageType | None:
        lower = text.lower()
        # Check multi-word patterns first (e.g. "search provider")
        for pkg_type, keywords in self.TYPE_PATTERNS.items():
            for kw in sorted(keywords, key=len, reverse=True):
                if kw in lower:
                    return pkg_type
        return None

    def _extract_query(
        self,
        text: str,
        action: PackageAction,
        pkg_type: PackageType | None,
    ) -> str:
        """Extract the search/target query from the text after removing
        action/type keywords and common filler words."""
        result = text.lower()

        # Remove action keywords
        for keywords in self.ACTION_PATTERNS.values():
            for kw in sorted(keywords, key=len, reverse=True):
                result = result.replace(kw, " ")

        # Remove type keywords
        for keywords in self.TYPE_PATTERNS.values():
            for kw in sorted(keywords, key=len, reverse=True):
                result = result.replace(kw, " ")

        # Remove common filler words
        fillers = [
            "the", "a", "an", "all", "my", "me", "for", "from",
            "installed", "available", "are", "is", "i", "please",
            "can", "you", "do", "and", "or", "with", "of",
        ]
        words = result.split()
        words = [w for w in words if w not in fillers]

        return " ".join(words).strip()


class PackageManager:
    """Unified package manager for tools, skills, MCP servers, and plugins.

    Provides a single conversational interface for all package operations.
    Each action delegates to the appropriate underlying manager.
    """

    def __init__(self) -> None:
        self._intent_parser = IntentParser()
        self._installed: dict[str, Package] = {}
        self._skill_store = None
        self._plugin_manager = None
        self._mcp_store = None
        self._tool_registry = None
        self._search_engine = None

    def set_backends(
        self,
        skill_store=None,
        plugin_manager=None,
        mcp_store=None,
        tool_registry=None,
        search_engine=None,
    ) -> None:
        """Inject backend dependencies."""
        if skill_store is not None:
            self._skill_store = skill_store
        if plugin_manager is not None:
            self._plugin_manager = plugin_manager
        if mcp_store is not None:
            self._mcp_store = mcp_store
        if tool_registry is not None:
            self._tool_registry = tool_registry
        if search_engine is not None:
            self._search_engine = search_engine

    async def handle_message(self, text: str) -> PackageActionResult:
        """Handle a natural language package management request."""
        action, pkg_type, query = self._intent_parser.parse(text)

        if pkg_type is None:
            pkg_type = self._infer_type(query)

        return await self._dispatch(action, pkg_type, query)

    async def _dispatch(
        self,
        action: PackageAction,
        pkg_type: PackageType | None,
        query: str,
    ) -> PackageActionResult:
        """Route action to appropriate handler."""
        handlers = {
            PackageAction.SEARCH: self._handle_search,
            PackageAction.INSTALL: self._handle_install,
            PackageAction.UNINSTALL: self._handle_uninstall,
            PackageAction.UPDATE: self._handle_update,
            PackageAction.ENABLE: self._handle_enable,
            PackageAction.DISABLE: self._handle_disable,
            PackageAction.LIST: self._handle_list,
            PackageAction.INFO: self._handle_info,
            PackageAction.STATUS: self._handle_status,
        }
        handler = handlers.get(action, self._handle_search)
        return await handler(pkg_type, query)

    # --- Dispatch handlers ---

    async def _handle_search(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        results = await self.search(query, pkg_type)
        pkg_type_out = pkg_type or PackageType.TOOL
        if not results:
            return PackageActionResult(
                success=True,
                action=PackageAction.SEARCH,
                package_type=pkg_type_out,
                package_name=query,
                message=f"No packages found matching '{query}'.",
                details={"results": []},
            )
        return PackageActionResult(
            success=True,
            action=PackageAction.SEARCH,
            package_type=pkg_type_out,
            package_name=query,
            message=f"Found {len(results)} package(s) matching '{query}'.",
            details={"results": [_package_to_dict(p) for p in results]},
        )

    async def _handle_install(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        if pkg_type is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.TOOL,
                package_name=query,
                message=f"Cannot determine package type for '{query}'. "
                "Please specify: tool, skill, mcp_server, or plugin.",
            )
        return await self.install(query, pkg_type)

    async def _handle_uninstall(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        if pkg_type is None:
            pkg_type = self._infer_type_from_installed(query)
        if pkg_type is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.UNINSTALL,
                package_type=PackageType.TOOL,
                package_name=query,
                message=f"Cannot determine package type for '{query}'.",
            )
        return await self.uninstall(query, pkg_type)

    async def _handle_update(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        # Update is treated as uninstall + install
        pkg_type_out = pkg_type or PackageType.TOOL
        return PackageActionResult(
            success=False,
            action=PackageAction.UPDATE,
            package_type=pkg_type_out,
            package_name=query,
            message="Update is not yet supported. "
            "Please uninstall and reinstall the package.",
        )

    async def _handle_enable(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        if pkg_type is None:
            pkg_type = self._infer_type_from_installed(query)
        if pkg_type is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.ENABLE,
                package_type=PackageType.TOOL,
                package_name=query,
                message=f"Cannot determine package type for '{query}'.",
            )
        return await self.enable(query, pkg_type)

    async def _handle_disable(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        if pkg_type is None:
            pkg_type = self._infer_type_from_installed(query)
        if pkg_type is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.DISABLE,
                package_type=PackageType.TOOL,
                package_name=query,
                message=f"Cannot determine package type for '{query}'.",
            )
        return await self.disable(query, pkg_type)

    async def _handle_list(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        packages = await self.list_packages(pkg_type)
        pkg_type_out = pkg_type or PackageType.TOOL
        return PackageActionResult(
            success=True,
            action=PackageAction.LIST,
            package_type=pkg_type_out,
            package_name="",
            message=f"Found {len(packages)} package(s).",
            details={"packages": [_package_to_dict(p) for p in packages]},
        )

    async def _handle_info(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        pkg = await self.get_info(query)
        pkg_type_out = pkg_type or PackageType.TOOL
        if pkg is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.INFO,
                package_type=pkg_type_out,
                package_name=query,
                message=f"Package '{query}' not found.",
            )
        return PackageActionResult(
            success=True,
            action=PackageAction.INFO,
            package_type=pkg.type,
            package_name=pkg.name,
            message=f"Package '{pkg.name}': {pkg.description}",
            details={"package": _package_to_dict(pkg)},
        )

    async def _handle_status(
        self, pkg_type: PackageType | None, query: str
    ) -> PackageActionResult:
        status = await self.get_status(pkg_type)
        pkg_type_out = pkg_type or PackageType.TOOL
        return PackageActionResult(
            success=True,
            action=PackageAction.STATUS,
            package_type=pkg_type_out,
            package_name="",
            message="Package status summary.",
            details={"status": status},
        )

    # --- Search ---

    async def search(
        self, query: str, pkg_type: PackageType | None = None, limit: int = 10
    ) -> list[Package]:
        """Search across all registries for packages matching query."""
        results: list[Package] = []

        if pkg_type is None or pkg_type == PackageType.SKILL:
            results.extend(await self._search_skills(query, limit))

        if pkg_type is None or pkg_type == PackageType.MCP_SERVER:
            results.extend(await self._search_mcp(query, limit))

        if pkg_type is None or pkg_type == PackageType.PLUGIN:
            results.extend(await self._search_plugins(query, limit))

        if pkg_type is None or pkg_type == PackageType.TOOL:
            results.extend(await self._search_tools(query, limit))

        return results[:limit]

    async def _search_skills(self, query: str, limit: int) -> list[Package]:
        if self._skill_store is None:
            return []
        try:
            skills = await self._skill_store.find_matching_skills(query, limit=limit)
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

    async def _search_mcp(self, query: str, limit: int) -> list[Package]:
        if self._mcp_store is None:
            return []
        try:
            results = await self._mcp_store.search(query, limit=limit)
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

    async def _search_plugins(self, query: str, _limit: int) -> list[Package]:
        if self._plugin_manager is None:
            return []
        try:
            manifests = await self._plugin_manager.discover()
            query_lower = query.lower()
            results = []
            for m in manifests:
                if query_lower in m.name.lower() or query_lower in m.description.lower():
                    loaded = m.name in self._plugin_manager.loaded_plugins
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

    async def _search_tools(self, query: str, _limit: int) -> list[Package]:
        if self._tool_registry is None:
            return []
        try:
            definitions = self._tool_registry.get_all_definitions()
            query_lower = query.lower()
            results = []
            for d in definitions:
                if query_lower in d.name.lower() or query_lower in d.description.lower():
                    source = self._tool_registry.get_tool_source(d.name)
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

    # --- Install ---

    async def install(
        self, name: str, pkg_type: PackageType, source: str = ""
    ) -> PackageActionResult:
        """Install a package by name and type."""
        handlers = {
            PackageType.SKILL: self.install_skill,
            PackageType.MCP_SERVER: self.install_mcp,
            PackageType.PLUGIN: self.install_plugin,
        }
        handler = handlers.get(pkg_type)
        if handler is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=pkg_type,
                package_name=name,
                message=f"Install not supported for type '{pkg_type.value}'.",
            )
        return await handler(name, source)

    async def install_skill(
        self, name: str, source: str = ""
    ) -> PackageActionResult:
        if self._skill_store is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.SKILL,
                package_name=name,
                message="SkillStore not available.",
            )
        try:
            skill = await self._skill_store.add_skill(
                name=name,
                description=f"Skill: {name}",
                prompt_template="",
                steps=[],
                trigger_keywords=[name],
                source=source or "package_manager",
            )
            pkg = Package(
                name=skill.name,
                type=PackageType.SKILL,
                description=skill.description,
                status="installed",
                source=skill.source,
            )
            self._track_installed(pkg)
            return PackageActionResult(
                success=True,
                action=PackageAction.INSTALL,
                package_type=PackageType.SKILL,
                package_name=name,
                message=f"Skill '{name}' installed successfully.",
            )
        except Exception as e:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.SKILL,
                package_name=name,
                message=f"Failed to install skill '{name}': {e}",
            )

    async def install_mcp(
        self, name: str, source: str = ""
    ) -> PackageActionResult:
        if self._mcp_store is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.MCP_SERVER,
                package_name=name,
                message="MCPStore not available.",
            )
        try:
            # Search for the server to get install details
            results = await self._mcp_store.search(name, limit=1)
            if not results:
                return PackageActionResult(
                    success=False,
                    action=PackageAction.INSTALL,
                    package_type=PackageType.MCP_SERVER,
                    package_name=name,
                    message=f"MCP server '{name}' not found in registries.",
                )
            server_meta = results[0]
            analysis = await self._mcp_store.analyze_server(server_meta)
            result = await self._mcp_store.install_server(
                name=name,
                slug=server_meta.get("slug", name),
                command=analysis.get("command", ""),
                args=analysis.get("args", []),
                source=source or server_meta.get("source", ""),
            )
            if result.get("status") == "ok":
                pkg = Package(
                    name=name,
                    type=PackageType.MCP_SERVER,
                    description=server_meta.get("description", ""),
                    status="installed",
                    source=source or server_meta.get("source", ""),
                    metadata=result,
                )
                self._track_installed(pkg)
                return PackageActionResult(
                    success=True,
                    action=PackageAction.INSTALL,
                    package_type=PackageType.MCP_SERVER,
                    package_name=name,
                    message=f"MCP server '{name}' installed with "
                    f"{result.get('tool_count', 0)} tools.",
                    details=result,
                )
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.MCP_SERVER,
                package_name=name,
                message=f"Failed to install MCP server '{name}': "
                f"{result.get('error', 'unknown error')}",
                details=result,
            )
        except Exception as e:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.MCP_SERVER,
                package_name=name,
                message=f"Failed to install MCP server '{name}': {e}",
            )

    async def install_plugin(
        self, name: str, source: str = ""
    ) -> PackageActionResult:
        if self._plugin_manager is None:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.PLUGIN,
                package_name=name,
                message="PluginManager not available.",
            )
        try:
            install_source = source or name
            manifest = await self._plugin_manager.install(install_source)
            pkg = Package(
                name=manifest.name,
                type=PackageType.PLUGIN,
                version=manifest.version,
                description=manifest.description,
                status="installed",
                source=source or "local",
            )
            self._track_installed(pkg)
            return PackageActionResult(
                success=True,
                action=PackageAction.INSTALL,
                package_type=PackageType.PLUGIN,
                package_name=manifest.name,
                message=f"Plugin '{manifest.name}' v{manifest.version} installed.",
            )
        except Exception as e:
            return PackageActionResult(
                success=False,
                action=PackageAction.INSTALL,
                package_type=PackageType.PLUGIN,
                package_name=name,
                message=f"Failed to install plugin '{name}': {e}",
            )

    # --- Uninstall ---

    async def uninstall(
        self, name: str, pkg_type: PackageType
    ) -> PackageActionResult:
        """Uninstall a package by name and type."""
        try:
            if pkg_type == PackageType.SKILL:
                if self._skill_store is None:
                    return self._backend_missing(
                        PackageAction.UNINSTALL, pkg_type, name, "SkillStore"
                    )
                removed = await self._skill_store.remove_skill(name)
                if not removed:
                    return PackageActionResult(
                        success=False,
                        action=PackageAction.UNINSTALL,
                        package_type=pkg_type,
                        package_name=name,
                        message=f"Skill '{name}' not found.",
                    )

            elif pkg_type == PackageType.MCP_SERVER:
                if self._mcp_store is None:
                    return self._backend_missing(
                        PackageAction.UNINSTALL, pkg_type, name, "MCPStore"
                    )
                result = await self._mcp_store.remove_server(name)
                if result.get("status") != "ok":
                    return PackageActionResult(
                        success=False,
                        action=PackageAction.UNINSTALL,
                        package_type=pkg_type,
                        package_name=name,
                        message=f"Failed to remove MCP server '{name}': "
                        f"{result.get('error', '')}",
                    )

            elif pkg_type == PackageType.PLUGIN:
                if self._plugin_manager is None:
                    return self._backend_missing(
                        PackageAction.UNINSTALL, pkg_type, name, "PluginManager"
                    )
                await self._plugin_manager.uninstall(name)

            elif pkg_type == PackageType.TOOL:
                if self._tool_registry is None:
                    return self._backend_missing(
                        PackageAction.UNINSTALL, pkg_type, name, "ToolRegistry"
                    )
                removed = self._tool_registry.unregister(name)
                if not removed:
                    return PackageActionResult(
                        success=False,
                        action=PackageAction.UNINSTALL,
                        package_type=pkg_type,
                        package_name=name,
                        message=f"Tool '{name}' not found.",
                    )
            else:
                return PackageActionResult(
                    success=False,
                    action=PackageAction.UNINSTALL,
                    package_type=pkg_type,
                    package_name=name,
                    message=f"Uninstall not supported for type '{pkg_type.value}'.",
                )

            self._untrack(name)
            return PackageActionResult(
                success=True,
                action=PackageAction.UNINSTALL,
                package_type=pkg_type,
                package_name=name,
                message=f"{pkg_type.value.capitalize()} '{name}' uninstalled.",
            )
        except Exception as e:
            return PackageActionResult(
                success=False,
                action=PackageAction.UNINSTALL,
                package_type=pkg_type,
                package_name=name,
                message=f"Failed to uninstall '{name}': {e}",
            )

    # --- Enable/Disable ---

    async def enable(
        self, name: str, pkg_type: PackageType
    ) -> PackageActionResult:
        """Enable a disabled package."""
        try:
            if pkg_type == PackageType.PLUGIN:
                if self._plugin_manager is None:
                    return self._backend_missing(
                        PackageAction.ENABLE, pkg_type, name, "PluginManager"
                    )
                result = await self._plugin_manager.load(name)
                if result is None:
                    return PackageActionResult(
                        success=False,
                        action=PackageAction.ENABLE,
                        package_type=pkg_type,
                        package_name=name,
                        message=f"Plugin '{name}' not found or failed to load.",
                    )
            else:
                # For tracked packages, update status
                pkg = self._installed.get(name)
                if pkg is None:
                    return PackageActionResult(
                        success=False,
                        action=PackageAction.ENABLE,
                        package_type=pkg_type,
                        package_name=name,
                        message=f"Package '{name}' not found.",
                    )
                pkg.status = "enabled"

            return PackageActionResult(
                success=True,
                action=PackageAction.ENABLE,
                package_type=pkg_type,
                package_name=name,
                message=f"{pkg_type.value.capitalize()} '{name}' enabled.",
            )
        except Exception as e:
            return PackageActionResult(
                success=False,
                action=PackageAction.ENABLE,
                package_type=pkg_type,
                package_name=name,
                message=f"Failed to enable '{name}': {e}",
            )

    async def disable(
        self, name: str, pkg_type: PackageType
    ) -> PackageActionResult:
        """Disable a package without uninstalling."""
        try:
            if pkg_type == PackageType.PLUGIN:
                if self._plugin_manager is None:
                    return self._backend_missing(
                        PackageAction.DISABLE, pkg_type, name, "PluginManager"
                    )
                await self._plugin_manager.unload(name)
            else:
                pkg = self._installed.get(name)
                if pkg is None:
                    return PackageActionResult(
                        success=False,
                        action=PackageAction.DISABLE,
                        package_type=pkg_type,
                        package_name=name,
                        message=f"Package '{name}' not found.",
                    )
                pkg.status = "disabled"

            return PackageActionResult(
                success=True,
                action=PackageAction.DISABLE,
                package_type=pkg_type,
                package_name=name,
                message=f"{pkg_type.value.capitalize()} '{name}' disabled.",
            )
        except Exception as e:
            return PackageActionResult(
                success=False,
                action=PackageAction.DISABLE,
                package_type=pkg_type,
                package_name=name,
                message=f"Failed to disable '{name}': {e}",
            )

    # --- List/Status ---

    async def list_packages(
        self,
        pkg_type: PackageType | None = None,
        status_filter: str | None = None,
    ) -> list[Package]:
        """List installed packages, optionally filtered by type/status."""
        packages: list[Package] = []

        if pkg_type is None or pkg_type == PackageType.TOOL:
            packages.extend(await self._list_tools())

        if pkg_type is None or pkg_type == PackageType.SKILL:
            packages.extend(await self._list_skills())

        if pkg_type is None or pkg_type == PackageType.MCP_SERVER:
            packages.extend(await self._list_mcp())

        if pkg_type is None or pkg_type == PackageType.PLUGIN:
            packages.extend(await self._list_plugins())

        if status_filter:
            packages = [p for p in packages if p.status == status_filter]

        return packages

    async def _list_tools(self) -> list[Package]:
        if self._tool_registry is None:
            return []
        try:
            definitions = self._tool_registry.get_all_definitions()
            return [
                Package(
                    name=d.name,
                    type=PackageType.TOOL,
                    description=d.description,
                    status="enabled",
                    source=self._tool_registry.get_tool_source(d.name),
                )
                for d in definitions
            ]
        except Exception:
            return []

    async def _list_skills(self) -> list[Package]:
        if self._skill_store is None:
            return []
        try:
            skills = await self._skill_store.list_skills()
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

    async def _list_mcp(self) -> list[Package]:
        if self._mcp_store is None:
            return []
        try:
            servers = await self._mcp_store.list_installed()
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

    async def _list_plugins(self) -> list[Package]:
        if self._plugin_manager is None:
            return []
        try:
            manifests = await self._plugin_manager.discover()
            loaded = self._plugin_manager.loaded_plugins
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

    async def get_status(
        self, pkg_type: PackageType | None = None
    ) -> dict:
        """Get status summary for all package types."""
        packages = await self.list_packages(pkg_type)
        summary: dict[str, Any] = {}
        for pt in PackageType:
            if pkg_type is not None and pt != pkg_type:
                continue
            type_pkgs = [p for p in packages if p.type == pt]
            summary[pt.value] = {
                "total": len(type_pkgs),
                "enabled": len([p for p in type_pkgs if p.status == "enabled"]),
                "disabled": len([p for p in type_pkgs if p.status == "disabled"]),
                "installed": len(
                    [p for p in type_pkgs if p.status == "installed"]
                ),
            }
        return summary

    async def get_info(self, name: str) -> Package | None:
        """Get detailed info about a specific package."""
        # Check tracked packages first
        if name in self._installed:
            return self._installed[name]

        # Check tool registry
        if self._tool_registry and self._tool_registry.has_tool(name):
            definitions = self._tool_registry.get_all_definitions()
            for d in definitions:
                if d.name == name:
                    return Package(
                        name=d.name,
                        type=PackageType.TOOL,
                        description=d.description,
                        status="enabled",
                        source=self._tool_registry.get_tool_source(name),
                    )

        # Check skill store
        if self._skill_store:
            skill = await self._skill_store.get_skill(name)
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

        # Check plugin manager
        if self._plugin_manager:
            manifest = self._plugin_manager.get_manifest(name)
            if manifest:
                loaded = name in self._plugin_manager.loaded_plugins
                return Package(
                    name=manifest.name,
                    type=PackageType.PLUGIN,
                    version=manifest.version,
                    description=manifest.description,
                    status="enabled" if loaded else "disabled",
                    source="local",
                )

        return None

    # --- Helpers ---

    def _infer_type(self, query: str) -> PackageType | None:
        """Try to infer package type from query content."""
        lower = query.lower()
        # Common MCP server names
        mcp_hints = ["server", "mcp", "github", "gitlab", "slack", "postgres"]
        if any(h in lower for h in mcp_hints):
            return PackageType.MCP_SERVER

        # Plugin hints
        plugin_hints = ["plugin", "extension"]
        if any(h in lower for h in plugin_hints):
            return PackageType.PLUGIN

        # Skill hints
        skill_hints = ["skill", "workflow", "template"]
        if any(h in lower for h in skill_hints):
            return PackageType.SKILL

        return None

    def _infer_type_from_installed(self, name: str) -> PackageType | None:
        """Try to find the package type from tracked installs."""
        pkg = self._installed.get(name)
        if pkg:
            return pkg.type
        return None

    def _track_installed(self, package: Package) -> None:
        self._installed[package.name] = package

    def _untrack(self, name: str) -> None:
        self._installed.pop(name, None)

    def _backend_missing(
        self,
        action: PackageAction,
        pkg_type: PackageType,
        name: str,
        backend_name: str,
    ) -> PackageActionResult:
        return PackageActionResult(
            success=False,
            action=action,
            package_type=pkg_type,
            package_name=name,
            message=f"{backend_name} not available.",
        )


def _package_to_dict(pkg: Package) -> dict:
    """Convert a Package to a serializable dict."""
    return {
        "name": pkg.name,
        "type": pkg.type.value,
        "version": pkg.version,
        "description": pkg.description,
        "status": pkg.status,
        "source": pkg.source,
        "metadata": pkg.metadata,
    }
