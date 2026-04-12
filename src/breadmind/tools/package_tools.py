"""Agent-facing tool functions that wrap the PackageManager.

These are registered with the ToolRegistry so the LLM agent can invoke
package management operations during conversation.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from breadmind.tools.registry import ToolResult, tool

if TYPE_CHECKING:
    from breadmind.tools.package_manager import PackageManager, PackageType


def create_package_tools(package_manager: PackageManager) -> list:
    """Create tool functions that wrap the PackageManager for agent use.

    Returns a list of @tool-decorated functions ready for registration
    with ToolRegistry.
    """
    from breadmind.tools.package_manager import PackageType

    def _type_or_none(type_str: str) -> PackageType | None:
        if not type_str:
            return None
        try:
            return PackageType(type_str)
        except ValueError:
            return None

    def _format_result(result) -> ToolResult:
        """Convert a PackageActionResult to a ToolResult."""
        output_parts = [result.message]
        if result.details:
            output_parts.append(json.dumps(result.details, indent=2, default=str))
        return ToolResult(
            success=result.success,
            output="\n".join(output_parts),
        )

    @tool(
        description=(
            "Search for installable packages (tools, skills, MCP servers, plugins). "
            "Args: query (search term), type (optional filter: tool/skill/mcp_server/plugin), "
            "limit (max results, default 10)."
        ),
        read_only=True,
        concurrency_safe=True,
    )
    async def pkg_search(query: str, type: str = "", limit: int = 10) -> ToolResult:
        pkg_type = _type_or_none(type)
        results = await package_manager.search(query, pkg_type, limit=limit)
        if not results:
            return ToolResult(success=True, output=f"No packages found matching '{query}'.")
        lines = []
        for i, pkg in enumerate(results, 1):
            lines.append(
                f"{i}. [{pkg.type.value}] **{pkg.name}** — {pkg.description} "
                f"(status: {pkg.status}, source: {pkg.source})"
            )
        return ToolResult(success=True, output="\n".join(lines))

    @tool(
        description=(
            "Install a package by name. "
            "Args: name (package name/slug), type (tool/skill/mcp_server/plugin), "
            "source (optional: git URL, marketplace slug, local path)."
        ),
    )
    async def pkg_install(name: str, type: str, source: str = "") -> ToolResult:
        pkg_type = _type_or_none(type)
        if pkg_type is None:
            return ToolResult(
                success=False,
                output=f"Invalid package type: '{type}'. "
                "Use: tool, skill, mcp_server, or plugin.",
            )
        result = await package_manager.install(name, pkg_type, source)
        return _format_result(result)

    @tool(
        description=(
            "Uninstall a package. "
            "Args: name (package name), type (tool/skill/mcp_server/plugin)."
        ),
    )
    async def pkg_uninstall(name: str, type: str) -> ToolResult:
        pkg_type = _type_or_none(type)
        if pkg_type is None:
            return ToolResult(
                success=False,
                output=f"Invalid package type: '{type}'.",
            )
        result = await package_manager.uninstall(name, pkg_type)
        return _format_result(result)

    @tool(
        description=(
            "List installed packages with their status. "
            "Args: type (optional filter), status (optional: installed/enabled/disabled)."
        ),
        read_only=True,
        concurrency_safe=True,
    )
    async def pkg_list(type: str = "", status: str = "") -> ToolResult:
        pkg_type = _type_or_none(type)
        packages = await package_manager.list_packages(
            pkg_type, status_filter=status or None
        )
        if not packages:
            return ToolResult(success=True, output="No packages found.")
        lines = []
        for pkg in packages:
            lines.append(
                f"[{pkg.type.value}] {pkg.name} — {pkg.status} "
                f"(source: {pkg.source})"
            )
        return ToolResult(success=True, output="\n".join(lines))

    @tool(
        description="Enable a disabled package. Args: name, type (tool/skill/mcp_server/plugin).",
    )
    async def pkg_enable(name: str, type: str) -> ToolResult:
        pkg_type = _type_or_none(type)
        if pkg_type is None:
            return ToolResult(success=False, output=f"Invalid package type: '{type}'.")
        result = await package_manager.enable(name, pkg_type)
        return _format_result(result)

    @tool(
        description=(
            "Disable a package without uninstalling. "
            "Args: name, type (tool/skill/mcp_server/plugin)."
        ),
    )
    async def pkg_disable(name: str, type: str) -> ToolResult:
        pkg_type = _type_or_none(type)
        if pkg_type is None:
            return ToolResult(success=False, output=f"Invalid package type: '{type}'.")
        result = await package_manager.disable(name, pkg_type)
        return _format_result(result)

    @tool(
        description="Show status summary of all managed packages (tools, skills, MCP, plugins).",
        read_only=True,
        concurrency_safe=True,
    )
    async def pkg_status() -> ToolResult:
        status = await package_manager.get_status()
        lines = []
        for type_name, counts in status.items():
            lines.append(
                f"{type_name}: {counts['total']} total "
                f"({counts.get('enabled', 0)} enabled, "
                f"{counts.get('disabled', 0)} disabled, "
                f"{counts.get('installed', 0)} installed)"
            )
        return ToolResult(success=True, output="\n".join(lines))

    @tool(
        description="Get detailed information about a specific package. Args: name (package name).",
        read_only=True,
        concurrency_safe=True,
    )
    async def pkg_info(name: str) -> ToolResult:
        pkg = await package_manager.get_info(name)
        if pkg is None:
            return ToolResult(success=False, output=f"Package '{name}' not found.")
        info = {
            "name": pkg.name,
            "type": pkg.type.value,
            "version": pkg.version,
            "description": pkg.description,
            "status": pkg.status,
            "source": pkg.source,
            "metadata": pkg.metadata,
        }
        return ToolResult(
            success=True,
            output=json.dumps(info, indent=2, default=str),
        )

    return [
        pkg_search,
        pkg_install,
        pkg_uninstall,
        pkg_list,
        pkg_enable,
        pkg_disable,
        pkg_status,
        pkg_info,
    ]
