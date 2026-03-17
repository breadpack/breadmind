"""Tool change detection — discovers newly installed or removed tools at runtime.

Extracted from env_scanner.py for SRP compliance.
Handles install/uninstall pattern matching, KG updates, and periodic reconciliation.
"""
from __future__ import annotations

import logging
import platform
import re
import shutil

from breadmind.core.env_detectors import run_cmd

logger = logging.getLogger(__name__)

# Install command patterns — when detected in shell_exec output, trigger tool discovery
_INSTALL_PATTERNS = re.compile(
    r"(?:successfully installed|is already installed|"
    r"Setting up |Unpacking |installed successfully|"
    r"choco install|winget install|scoop install|"
    r"apt install|yum install|dnf install|brew install|"
    r"pip install|npm install|cargo install|go install|"
    r"Installation complete|installed \d+ package)",
    re.I,
)

_UNINSTALL_PATTERNS = re.compile(
    r"(?:successfully uninstalled|removed|purged|"
    r"uninstalled successfully|has been removed|"
    r"choco uninstall|winget uninstall|scoop uninstall|"
    r"apt remove|apt-get remove|apt purge|yum remove|dnf remove|"
    r"brew uninstall|pip uninstall|npm uninstall|"
    r"cargo uninstall|Removing )",
    re.I,
)


def _extract_tool_from_install_cmd(command: str) -> str | None:
    """Extract the tool/package name from an install command."""
    patterns = [
        re.compile(r"pip3?\s+install\s+(?:-[^\s]+\s+)*([a-zA-Z0-9_-]+)", re.I),
        re.compile(r"npm\s+install\s+(?:-[^\s]+\s+)*([a-zA-Z0-9@/_-]+)", re.I),
        re.compile(r"(?:apt|yum|dnf|apt-get)\s+install\s+(?:-[^\s]+\s+)*([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"brew\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"choco\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"winget\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"scoop\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"cargo\s+install\s+([a-zA-Z0-9_-]+)", re.I),
        re.compile(r"go\s+install\s+([a-zA-Z0-9./_-]+)", re.I),
    ]
    for pat in patterns:
        m = pat.search(command)
        if m:
            name = m.group(1).split("/")[-1].split("@")[0]
            return name
    return None


def _extract_tool_from_uninstall_cmd(command: str) -> str | None:
    """Extract the tool/package name from an uninstall command."""
    patterns = [
        re.compile(r"pip3?\s+uninstall\s+(?:-[^\s]+\s+)*([a-zA-Z0-9_-]+)", re.I),
        re.compile(r"npm\s+(?:uninstall|remove)\s+(?:-[^\s]+\s+)*([a-zA-Z0-9@/_-]+)", re.I),
        re.compile(r"(?:apt|apt-get)\s+(?:remove|purge)\s+(?:-[^\s]+\s+)*([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"(?:yum|dnf)\s+(?:remove|erase)\s+(?:-[^\s]+\s+)*([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"brew\s+uninstall\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"choco\s+uninstall\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"winget\s+uninstall\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"scoop\s+uninstall\s+([a-zA-Z0-9._-]+)", re.I),
        re.compile(r"cargo\s+uninstall\s+([a-zA-Z0-9_-]+)", re.I),
    ]
    for pat in patterns:
        m = pat.search(command)
        if m:
            name = m.group(1).split("/")[-1].split("@")[0]
            return name
    return None


async def detect_new_tool(command: str, output: str, semantic_memory) -> str | None:
    """Check if a shell command installed a new tool and update KG if so.

    Called after shell_exec completes. Returns tool name if detected, else None.
    Lightweight: no LLM, just pattern matching + shutil.which.
    """
    if not output or not semantic_memory:
        return None

    if not _INSTALL_PATTERNS.search(output):
        return None

    tool_name = _extract_tool_from_install_cmd(command)
    if not tool_name:
        return None

    if not shutil.which(tool_name):
        return None

    entity_id = f"tool:{tool_name}"
    existing = await semantic_memory.get_entity(entity_id)
    if existing:
        return None

    version = "installed"
    try:
        ok, ver = await run_cmd(f"{tool_name} --version", timeout=5)
        if ok and ver:
            version = ver.splitlines()[0][:80]
    except Exception:
        pass

    from breadmind.storage.models import KGEntity, KGRelation
    hostname = platform.node()

    await semantic_memory.add_entity(KGEntity(
        id=entity_id,
        entity_type="infra_component",
        name=tool_name,
        properties={"version": version, "host": hostname, "discovered": "runtime"},
    ))
    await semantic_memory.add_relation(KGRelation(
        source_id=f"host:{hostname}",
        target_id=entity_id,
        relation_type="has_tool",
    ))

    logger.info("New tool discovered at runtime: %s (%s)", tool_name, version)
    return tool_name


async def detect_removed_tool(command: str, output: str, semantic_memory) -> str | None:
    """Check if a shell command removed a tool and update KG if so.

    Called after shell_exec completes. Returns tool name if detected, else None.
    """
    if not output or not semantic_memory:
        return None

    if not _UNINSTALL_PATTERNS.search(output):
        return None

    tool_name = _extract_tool_from_uninstall_cmd(command)
    if not tool_name:
        return None

    if shutil.which(tool_name):
        return None

    entity_id = f"tool:{tool_name}"
    existing = await semantic_memory.get_entity(entity_id)
    if not existing:
        return None

    semantic_memory._entities.pop(entity_id, None)
    semantic_memory._relations = [
        r for r in semantic_memory._relations
        if r.source_id != entity_id and r.target_id != entity_id
    ]

    logger.info("Tool removed detected at runtime: %s", tool_name)
    return tool_name


async def reconcile_tools(semantic_memory) -> list[str]:
    """Check all tool entities in KG and remove those no longer installed.

    Called during periodic tool rescan. Returns list of removed tool names.
    """
    removed: list[str] = []
    tool_entities = [
        (eid, e) for eid, e in list(semantic_memory._entities.items())
        if eid.startswith("tool:") and e.entity_type == "infra_component"
    ]

    for entity_id, entity in tool_entities:
        tool_name = entity_id[5:]  # Strip "tool:" prefix
        if tool_name in ("docker", "kubernetes"):
            continue
        if not shutil.which(tool_name):
            semantic_memory._entities.pop(entity_id, None)
            semantic_memory._relations = [
                r for r in semantic_memory._relations
                if r.source_id != entity_id and r.target_id != entity_id
            ]
            removed.append(tool_name)
            logger.info("Tool no longer found: %s (removed from KG)", tool_name)

    return removed
