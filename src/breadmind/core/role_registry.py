"""Role definitions and tool-set mappings for orchestrator subagents."""
from __future__ import annotations

from dataclasses import dataclass, field

logger = __import__("logging").getLogger(__name__)


@dataclass
class RoleDefinition:
    name: str              # e.g. "k8s_diagnostician"
    domain: str            # e.g. "k8s"
    task_type: str         # e.g. "diagnostician"
    system_prompt: str
    description: str = ""
    dedicated_tools: list[str] = field(default_factory=list)
    common_tools: list[str] = field(default_factory=list)


_COMMON_TOOLS = ["shell_exec", "file_read", "file_write", "web_search"]

_DIFFICULTY_MODEL: dict[str, str] = {
    "low": "haiku",
    "medium": "sonnet",
    "high": "opus",
}

_BUILTIN_ROLES: list[RoleDefinition] = [
    RoleDefinition(
        name="k8s_diagnostician",
        domain="k8s",
        task_type="diagnostician",
        system_prompt=(
            "You are a Kubernetes diagnostician. Investigate cluster health, "
            "pod states, events, and resource usage to identify root causes."
        ),
        description="Diagnoses Kubernetes cluster issues using read-only operations.",
        dedicated_tools=[
            "pods_list", "pods_get", "pods_log", "pods_top",
            "nodes_top", "nodes_stats_summary",
            "events_list", "resources_list", "resources_get", "namespaces_list",
        ],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="k8s_executor",
        domain="k8s",
        task_type="executor",
        system_prompt=(
            "You are a Kubernetes executor. Apply changes to cluster resources "
            "such as creating, updating, deleting, scaling, and running workloads."
        ),
        description="Performs write operations on Kubernetes cluster resources.",
        dedicated_tools=[
            "pods_list", "pods_get", "pods_delete", "pods_run",
            "resources_create_or_update", "resources_delete", "resources_get",
            "resources_list", "resources_scale", "namespaces_list",
        ],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="proxmox_diagnostician",
        domain="proxmox",
        task_type="diagnostician",
        system_prompt=(
            "You are a Proxmox diagnostician. Inspect VMs, nodes, storage, "
            "cluster health, and backup/snapshot status to assess the environment."
        ),
        description="Diagnoses Proxmox VE environments using read-only operations.",
        dedicated_tools=[
            "proxmox_get_vms", "proxmox_get_vm_status",
            "proxmox_get_nodes", "proxmox_get_node_status",
            "proxmox_get_storage", "proxmox_get_cluster_status",
            "proxmox_list_backups", "proxmox_list_snapshots_vm",
            "proxmox_list_snapshots_lxc",
        ],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="proxmox_executor",
        domain="proxmox",
        task_type="executor",
        system_prompt=(
            "You are a Proxmox executor. Manage VM and LXC lifecycles including "
            "start, stop, reboot, resize, clone, snapshot, and backup operations."
        ),
        description="Performs write operations on Proxmox VE VMs and LXC containers.",
        dedicated_tools=[
            "proxmox_get_vms", "proxmox_get_vm_status",
            "proxmox_start_vm", "proxmox_stop_vm", "proxmox_reboot_vm",
            "proxmox_resize_vm", "proxmox_clone_vm",
            "proxmox_create_snapshot_vm", "proxmox_create_backup_vm",
            "proxmox_start_lxc", "proxmox_stop_lxc", "proxmox_reboot_lxc",
        ],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="openwrt_diagnostician",
        domain="openwrt",
        task_type="diagnostician",
        system_prompt=(
            "You are an OpenWrt diagnostician. Inspect network interfaces, "
            "system status, and logs to identify connectivity or configuration issues."
        ),
        description="Diagnoses OpenWrt router/network issues using read-only operations.",
        dedicated_tools=["network_status", "system_status", "read_log"],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="openwrt_executor",
        domain="openwrt",
        task_type="executor",
        system_prompt=(
            "You are an OpenWrt executor. Manage network and system operations "
            "such as rebooting the device and toggling LED states."
        ),
        description="Performs write operations on OpenWrt routers.",
        dedicated_tools=["network_status", "system_status", "read_log", "reboot", "set_led_state"],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="general_analyst",
        domain="general",
        task_type="analyst",
        system_prompt=(
            "You are a general analyst. Investigate and synthesize information "
            "from any available source to answer questions and surface insights."
        ),
        description="General-purpose analysis across any domain.",
        dedicated_tools=[],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="security_analyst",
        domain="security",
        task_type="analyst",
        system_prompt=(
            "You are a security analyst. Evaluate configurations, access patterns, "
            "and log data to identify vulnerabilities and security risks."
        ),
        description="Assesses security posture and identifies risks.",
        dedicated_tools=[],
        common_tools=list(_COMMON_TOOLS),
    ),
    RoleDefinition(
        name="performance_analyst",
        domain="performance",
        task_type="analyst",
        system_prompt=(
            "You are a performance analyst. Examine metrics, resource utilisation, "
            "and bottlenecks to provide actionable performance improvement recommendations."
        ),
        description="Analyses system and application performance.",
        dedicated_tools=[],
        common_tools=list(_COMMON_TOOLS),
    ),
]


class RoleRegistry:
    """Registry of subagent role definitions and their associated tool sets."""

    def __init__(self) -> None:
        self._roles: dict[str, RoleDefinition] = {
            role.name: role for role in _BUILTIN_ROLES
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get(self, name: str) -> RoleDefinition | None:
        """Return a role by name, or None if not found."""
        return self._roles.get(name)

    def list_roles(self) -> list[RoleDefinition]:
        """Return all registered roles."""
        return list(self._roles.values())

    def register(self, role: RoleDefinition) -> None:
        """Register a new role (or replace an existing one with the same name)."""
        self._roles[role.name] = role
        logger.debug("Registered role: %s", role.name)

    def remove(self, name: str) -> bool:
        """Remove a role by name. Returns True if removed, False if not found."""
        if name in self._roles:
            del self._roles[name]
            logger.debug("Removed role: %s", name)
            return True
        return False

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def get_tools(self, role_name: str) -> list[str]:
        """Return the combined tool list (dedicated + common) for a role.

        Falls back to common-only tools when the role is not found.
        """
        role = self._roles.get(role_name)
        if role is None:
            return list(_COMMON_TOOLS)
        # Deduplicate while preserving order (dedicated first).
        seen: set[str] = set()
        tools: list[str] = []
        for t in role.dedicated_tools + role.common_tools:
            if t not in seen:
                seen.add(t)
                tools.append(t)
        return tools

    def get_prompt(self, role_name: str) -> str:
        """Return the system prompt for a role, or an empty string if not found."""
        role = self._roles.get(role_name)
        return role.system_prompt if role is not None else ""

    # ------------------------------------------------------------------
    # Model mapping
    # ------------------------------------------------------------------

    @staticmethod
    def difficulty_to_model(difficulty: str) -> str:
        """Map a difficulty label to a model tier name.

        Known values: "low" -> "haiku", "medium" -> "sonnet", "high" -> "opus".
        Unknown values default to "sonnet".
        """
        return _DIFFICULTY_MODEL.get(difficulty, "sonnet")

    # ------------------------------------------------------------------
    # Summary for Planner
    # ------------------------------------------------------------------

    def list_role_summaries(self) -> str:
        """Return a formatted string listing all roles, suitable for a Planner prompt."""
        lines: list[str] = ["Available subagent roles:"]
        for role in self._roles.values():
            tool_preview = ", ".join(role.dedicated_tools[:5])
            if len(role.dedicated_tools) > 5:
                tool_preview += f", ... (+{len(role.dedicated_tools) - 5} more)"
            desc = role.description or role.system_prompt[:80]
            lines.append(
                f"  - {role.name} [{role.domain}/{role.task_type}]: {desc}"
                + (f" | tools: {tool_preview}" if tool_preview else "")
            )
        return "\n".join(lines)
