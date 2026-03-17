"""Comprehensive environment scanner — discovers and memorizes the host system.

Runs on first startup (or on demand) to build a complete picture of:
- OS, CPU, memory, disk
- Installed CLI tools and package managers
- Infrastructure tools (Docker, K8s, Proxmox, etc.)
- Network configuration
- Running services

Results are stored as pinned episodic memories + KG entities
so the agent can reference them in future conversations.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
from dataclasses import dataclass, field

from breadmind.core.env_detectors import (
    scan_cpu,
    scan_disks,
    scan_infra,
    scan_memory,
    scan_network,
    scan_services,
    scan_tools,
)
from breadmind.core.tool_change_detector import (  # noqa: F401 — re-export
    _extract_tool_from_install_cmd,
    _extract_tool_from_uninstall_cmd,
    detect_new_tool,
    detect_removed_tool,
    reconcile_tools,
)

logger = logging.getLogger(__name__)

# Re-export all public names so existing ``from breadmind.core.env_scanner import …``
# statements keep working without changes.
__all__ = [
    "ScanResult",
    "scan_environment",
    "scan_dynamic",
    "store_scan_in_memory",
    "detect_new_tool",
    "detect_removed_tool",
    "reconcile_tools",
    "_extract_tool_from_install_cmd",
    "_extract_tool_from_uninstall_cmd",
]


@dataclass
class ScanResult:
    """Complete environment scan result."""
    # System
    hostname: str = ""
    os_name: str = ""
    os_version: str = ""
    os_arch: str = ""
    cpu_info: str = ""
    cpu_cores: int = 0
    memory_total_gb: float = 0.0
    memory_available_gb: float = 0.0

    # Disks
    disks: list[dict] = field(default_factory=list)  # [{drive, total_gb, free_gb, percent_used}]

    # Tools & Package Managers
    installed_tools: dict[str, str] = field(default_factory=dict)  # {tool_name: version}
    package_managers: list[str] = field(default_factory=list)

    # Infrastructure
    docker_version: str = ""
    k8s_version: str = ""
    k8s_contexts: list[str] = field(default_factory=list)
    k8s_current_context: str = ""

    # Network
    ip_addresses: list[str] = field(default_factory=list)
    open_listeners: list[dict] = field(default_factory=list)  # [{port, process}]

    # Services
    running_services: list[str] = field(default_factory=list)

    def to_memory_text(self) -> str:
        """Convert to structured text for memory storage."""
        lines = [
            f"## Host Environment: {self.hostname}",
            f"- OS: {self.os_name} {self.os_version} ({self.os_arch})",
            f"- CPU: {self.cpu_info} ({self.cpu_cores} cores)",
            f"- Memory: {self.memory_available_gb:.1f}GB available / {self.memory_total_gb:.1f}GB total",
        ]

        if self.disks:
            lines.append("- Disks:")
            for d in self.disks:
                lines.append(f"  - {d['drive']}: {d['free_gb']:.0f}GB free / {d['total_gb']:.0f}GB ({d['percent_used']:.0f}% used)")

        if self.installed_tools:
            lines.append(f"- Installed tools: {', '.join(sorted(self.installed_tools.keys()))}")

        if self.package_managers:
            lines.append(f"- Package managers: {', '.join(self.package_managers)}")

        if self.docker_version:
            lines.append(f"- Docker: {self.docker_version}")
        if self.k8s_version:
            ctx = f" (context: {self.k8s_current_context})" if self.k8s_current_context else ""
            lines.append(f"- Kubernetes: {self.k8s_version}{ctx}")
            if self.k8s_contexts:
                lines.append(f"  - Contexts: {', '.join(self.k8s_contexts)}")

        if self.ip_addresses:
            lines.append(f"- IP addresses: {', '.join(self.ip_addresses)}")

        if self.running_services:
            lines.append(f"- Notable services: {', '.join(self.running_services[:20])}")

        return "\n".join(lines)

    def to_keywords(self) -> list[str]:
        """Extract keywords for memory indexing."""
        kws = [self.hostname.lower(), self.os_name.lower()]
        kws.extend(self.installed_tools.keys())
        kws.extend(self.package_managers)
        if self.docker_version:
            kws.append("docker")
        if self.k8s_version:
            kws.append("kubernetes")
        kws.extend(self.ip_addresses)
        return list(set(kw for kw in kws if kw))


async def scan_environment() -> ScanResult:
    """Perform a comprehensive environment scan."""
    result = ScanResult()

    # Basic system info
    result.hostname = platform.node()
    result.os_name = platform.system()
    result.os_version = platform.version()
    result.os_arch = platform.machine()
    result.cpu_cores = os.cpu_count() or 0

    # Run all scans concurrently
    await asyncio.gather(
        scan_cpu(result),
        scan_memory(result),
        scan_disks(result),
        scan_tools(result),
        scan_infra(result),
        scan_network(result),
        scan_services(result),
    )

    return result


async def scan_dynamic(include_tools: bool = False) -> ScanResult:
    """Lightweight scan of only dynamic (changing) data: memory, disks, IPs, services.

    Args:
        include_tools: If True, also rescan installed tools (slower, ~5s).
    """
    result = ScanResult()
    result.hostname = platform.node()
    result.os_name = platform.system()
    result.os_version = platform.version()
    result.os_arch = platform.machine()
    result.cpu_cores = os.cpu_count() or 0

    tasks = [
        scan_memory(result),
        scan_disks(result),
        scan_network(result),
        scan_services(result),
    ]
    if include_tools:
        tasks.append(scan_tools(result))
        tasks.append(scan_infra(result))

    await asyncio.gather(*tasks)

    return result


async def store_scan_in_memory(
    scan: ScanResult,
    episodic_memory,
    semantic_memory,
    db=None,
) -> dict:
    """Store scan results as pinned memories and KG entities.

    If an env_scan note already exists, it is replaced (not duplicated).
    KG entities are upserted (add_entity overwrites by ID).

    Returns stats about what was stored.
    """
    from breadmind.storage.models import KGEntity, KGRelation

    stored = {"notes": 0, "entities": 0, "updated": False}

    # 1. Find and replace existing env_scan note, or create new
    existing_note = None
    for note in episodic_memory._notes:
        if "env_scan" in (note.tags or []):
            existing_note = note
            break

    if existing_note is not None:
        # Update in place — preserve pin status and access history
        existing_note.content = scan.to_memory_text()
        existing_note.keywords = scan.to_keywords()
        existing_note.context_description = f"Environment scan of {scan.hostname}"
        from datetime import datetime, timezone
        existing_note.updated_at = datetime.now(timezone.utc)
        stored["updated"] = True
    else:
        note = await episodic_memory.add_note(
            content=scan.to_memory_text(),
            keywords=scan.to_keywords(),
            tags=["env_scan", "system_info", "pinned"],
            context_description=f"Environment scan of {scan.hostname}",
        )
        episodic_memory.pin_note(note)
    stored["notes"] = 1

    # 2. Upsert KG entities for the host
    host_entity = KGEntity(
        id=f"host:{scan.hostname}",
        entity_type="infra_component",
        name=scan.hostname,
        properties={
            "os": f"{scan.os_name} {scan.os_version}",
            "arch": scan.os_arch,
            "cpu": scan.cpu_info,
            "cpu_cores": scan.cpu_cores,
            "memory_total_gb": round(scan.memory_total_gb, 1),
            "memory_available_gb": round(scan.memory_available_gb, 1),
        },
    )
    await semantic_memory.add_entity(host_entity)
    stored["entities"] += 1

    # 3. Upsert entities for each IP address
    old_rels = await semantic_memory.get_relations(f"host:{scan.hostname}")
    old_ip_ids = {r.target_id for r in old_rels if r.relation_type == "has_address"}
    new_ip_ids = {f"ip:{ip}" for ip in scan.ip_addresses}

    for stale_id in old_ip_ids - new_ip_ids:
        semantic_memory._entities.pop(stale_id, None)

    for ip in scan.ip_addresses:
        ip_entity = KGEntity(
            id=f"ip:{ip}",
            entity_type="infra_component",
            name=ip,
            properties={"type": "ip_address", "host": scan.hostname},
        )
        await semantic_memory.add_entity(ip_entity)
        if f"ip:{ip}" not in old_ip_ids:
            await semantic_memory.add_relation(KGRelation(
                source_id=f"host:{scan.hostname}",
                target_id=f"ip:{ip}",
                relation_type="has_address",
            ))
        stored["entities"] += 1

    # 4. Upsert entities for infrastructure tools
    for tool_name in ["docker", "kubernetes"]:
        version = ""
        if tool_name == "docker" and scan.docker_version:
            version = scan.docker_version
        elif tool_name == "kubernetes" and scan.k8s_version:
            version = scan.k8s_version
        else:
            continue

        tool_entity = KGEntity(
            id=f"tool:{tool_name}",
            entity_type="infra_component",
            name=tool_name,
            properties={"version": version, "host": scan.hostname},
        )
        await semantic_memory.add_entity(tool_entity)
        stored["entities"] += 1

    # 5. Upsert entities for disks (with latest usage)
    for disk in scan.disks:
        disk_entity = KGEntity(
            id=f"disk:{scan.hostname}:{disk['drive']}",
            entity_type="infra_component",
            name=f"{scan.hostname}:{disk['drive']}",
            properties={
                "total_gb": round(disk["total_gb"], 1),
                "free_gb": round(disk["free_gb"], 1),
                "percent_used": round(disk["percent_used"], 1),
            },
        )
        await semantic_memory.add_entity(disk_entity)
        stored["entities"] += 1

    # 6. Save scan timestamp in DB
    if db:
        try:
            from datetime import datetime, timezone
            await db.set_setting("last_env_scan", {
                "hostname": scan.hostname,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tools_count": len(scan.installed_tools),
                "disks_count": len(scan.disks),
            })
        except Exception:
            pass

    action = "updated" if stored["updated"] else "stored"
    logger.info(
        "Environment scan %s: %d notes, %d entities (host=%s, tools=%d, disks=%d)",
        action, stored["notes"], stored["entities"],
        scan.hostname, len(scan.installed_tools), len(scan.disks),
    )

    return stored
