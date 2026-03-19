import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class SwarmTask:
    id: str
    description: str
    role: str  # Which expert role should handle this
    depends_on: list[str] = field(default_factory=list)  # Task IDs this depends on
    status: str = "pending"  # pending, running, completed, failed
    result: str = ""
    error: str = ""


@dataclass
class SwarmContext:
    """Shared state across swarm members."""
    task_graph: dict[str, SwarmTask] = field(default_factory=dict)
    findings: list[dict] = field(default_factory=list)
    final_result: str = ""


@dataclass
class SwarmMember:
    role: str
    system_prompt: str
    description: str = ""
    source: str = "manual"


DEFAULT_ROLES: dict[str, SwarmMember] = {
    "k8s_expert": SwarmMember(
        role="k8s_expert",
        system_prompt=(
            "You are a Kubernetes cluster expert responsible for comprehensive cluster health analysis.\n"
            "Your primary objective is to diagnose issues and report actionable findings.\n\n"
            "Check items:\n"
            "1. Node status — check for NotReady, SchedulingDisabled, or resource pressure conditions.\n"
            "2. Pod health — identify CrashLoopBackOff, ImagePullBackOff, OOMKilled, and pending pods.\n"
            "3. Resource usage — compare CPU/memory requests vs limits vs actual utilization per node.\n"
            "4. Deployments & ReplicaSets — verify desired vs available replicas, rollout status.\n"
            "5. Events — surface recent warning-level cluster events.\n\n"
            "Use Kubernetes MCP tools: pods_list, pods_get, pods_log, nodes_top, pods_top,\n"
            "resources_list, resources_get, events_list, namespaces_list.\n\n"
            "Output format: classify each finding as [Critical], [Warning], or [OK] with a one-line summary."
        ),
        description="Kubernetes cluster analysis and management",
    ),
    "proxmox_expert": SwarmMember(
        role="proxmox_expert",
        system_prompt=(
            "You are a Proxmox virtualization expert responsible for hypervisor and guest health analysis.\n"
            "Your primary objective is to ensure all VMs and LXC containers are running optimally.\n\n"
            "Check items:\n"
            "1. VM/LXC status — identify stopped, paused, or unresponsive guests.\n"
            "2. Resource allocation — check CPU, memory, and disk over-commitment ratios.\n"
            "3. Storage health — verify available space on each storage pool and detect thin-provision risks.\n"
            "4. Backup status — confirm recent backups exist and check for failed backup jobs.\n"
            "5. Cluster/node health — review node status, HA group configuration, and quorum.\n\n"
            "Use Proxmox MCP tools: proxmox_get_vms, proxmox_get_vm_status, proxmox_get_nodes,\n"
            "proxmox_get_node_status, proxmox_get_storage, proxmox_list_backups,\n"
            "proxmox_get_cluster_status, proxmox_list_snapshots_vm, proxmox_list_snapshots_lxc.\n\n"
            "Output format: classify each finding as [Critical], [Warning], or [OK] with a one-line summary."
        ),
        description="Proxmox virtualization management",
    ),
    "openwrt_expert": SwarmMember(
        role="openwrt_expert",
        system_prompt=(
            "You are an OpenWrt and network infrastructure expert.\n"
            "Your primary objective is to ensure network connectivity, security, and proper configuration.\n\n"
            "Check items:\n"
            "1. Network interfaces — verify WAN/LAN link status, IP assignments, and VLAN configuration.\n"
            "2. Firewall rules — check for overly permissive rules, missing input drops, and port forwards.\n"
            "3. DHCP leases — review active leases, static assignments, and pool exhaustion.\n"
            "4. DNS configuration — verify upstream resolvers, local DNS entries, and rebind protection.\n"
            "5. System health — check uptime, CPU/memory usage, and kernel log for errors.\n\n"
            "Use OpenWrt MCP tools: network_status, system_status, read_log, reboot, set_led_state.\n\n"
            "Output format: classify each finding as [Critical], [Warning], or [OK] with a one-line summary."
        ),
        description="Network and OpenWrt management",
    ),
    "security_analyst": SwarmMember(
        role="security_analyst",
        system_prompt=(
            "You are a security analyst responsible for infrastructure security posture assessment.\n"
            "Your primary objective is to identify vulnerabilities, misconfigurations, and compliance gaps.\n\n"
            "Check items:\n"
            "1. RBAC & access control — review Kubernetes RBAC bindings, Proxmox user permissions,\n"
            "   and service accounts with excessive privileges.\n"
            "2. Firewall & network exposure — identify services exposed to the internet, missing network\n"
            "   policies, and insecure port forwards.\n"
            "3. Certificate expiration — check TLS certificates for upcoming expiry (< 30 days).\n"
            "4. Known CVEs — flag containers running images with known critical vulnerabilities.\n"
            "5. Authentication — verify MFA enforcement, default credentials, and API key rotation.\n\n"
            "Use all available MCP tool categories (Kubernetes, Proxmox, OpenWrt) to cross-reference\n"
            "security findings across the infrastructure stack.\n\n"
            "Output format: classify each finding as [Critical], [Warning], or [OK] with a one-line summary."
        ),
        description="Security analysis and vulnerability assessment",
    ),
    "performance_analyst": SwarmMember(
        role="performance_analyst",
        system_prompt=(
            "You are a performance analyst responsible for resource utilization and capacity planning.\n"
            "Your primary objective is to identify bottlenecks, waste, and forecast capacity needs.\n\n"
            "Check items:\n"
            "1. CPU trends — identify sustained high usage (> 80%) or idle waste across nodes and VMs.\n"
            "2. Memory pressure — detect OOM risks, swap usage, and over-committed memory.\n"
            "3. Disk I/O & storage — find slow volumes, high IOPS queues, and storage nearing capacity.\n"
            "4. Network throughput — identify saturated links, high latency, and packet loss.\n"
            "5. Capacity planning — project when resources will be exhausted based on current growth.\n\n"
            "Use Kubernetes MCP tools (nodes_top, pods_top, nodes_stats_summary) and Proxmox MCP\n"
            "tools (proxmox_get_node_status, proxmox_get_vm_status) for data collection.\n\n"
            "Output format: classify each finding as [Critical], [Warning], or [OK] with a one-line summary.\n"
            "Include optimization recommendations with estimated resource savings where possible."
        ),
        description="Performance analysis and optimization",
    ),
    "general": SwarmMember(
        role="general",
        system_prompt=(
            "You are a general-purpose infrastructure assistant and the fallback analyst.\n"
            "Your primary objective is to handle tasks that do not fit a specialized role.\n\n"
            "Check items:\n"
            "1. Interpret the task description and gather relevant data from any available MCP tools.\n"
            "2. Cross-reference findings across Kubernetes, Proxmox, and OpenWrt where applicable.\n"
            "3. Provide a clear, structured analysis even when the domain is ambiguous.\n\n"
            "Use any available MCP tool category as needed (Kubernetes, Proxmox, OpenWrt).\n\n"
            "Output format: classify each finding as [Critical], [Warning], or [OK] with a one-line summary.\n"
            "When unsure of severity, default to [Warning] and explain your reasoning."
        ),
        description="General-purpose analysis (fallback)",
    ),
}


def _render_role_prompt(role_vars: dict) -> str:
    parts = []
    if role_vars.get("role_name"):
        parts.append(f"You are a {role_vars['role_name']}.")
    if role_vars.get("expertise"):
        parts.append(f"Expertise: {role_vars['expertise']}")
    if role_vars.get("decision_criteria"):
        parts.append(f"Decision criteria: {role_vars['decision_criteria']}")
    if role_vars.get("domain_context"):
        parts.append(role_vars["domain_context"])
    if role_vars.get("preferred_tools"):
        tools = role_vars["preferred_tools"]
        if isinstance(tools, list):
            parts.append(f"Use tools: {', '.join(tools)}")
    parts.append("Output format: classify each finding as [Critical], [Warning], or [OK] with a one-line summary.")
    return "\n\n".join(parts)


def build_default_roles(prompt_builder=None) -> dict[str, SwarmMember]:
    """Build default roles. Uses PromptBuilder templates if available, falls back to hardcoded."""
    if prompt_builder is None:
        return dict(DEFAULT_ROLES)

    roles = {}
    role_configs = {
        "k8s_expert": "Kubernetes cluster analysis and management",
        "proxmox_expert": "Proxmox virtualization management",
        "openwrt_expert": "Network and OpenWrt management",
        "security_analyst": "Security analysis and vulnerability assessment",
        "performance_analyst": "Performance analysis and optimization",
        "general": "General-purpose analysis (fallback)",
    }

    for role_name, description in role_configs.items():
        role_vars = prompt_builder._load_role(role_name, None)
        if role_vars:
            system_prompt = _render_role_prompt(role_vars)
            roles[role_name] = SwarmMember(
                role=role_name,
                system_prompt=system_prompt,
                description=description,
                source="template",
            )
        elif role_name in DEFAULT_ROLES:
            roles[role_name] = DEFAULT_ROLES[role_name]

    return roles


@dataclass
class SwarmResult:
    id: str
    goal: str
    status: str = "pending"  # pending, running, completed, failed
    tasks: list[dict] = field(default_factory=list)
    final_result: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error: str = ""


class SwarmManager:
    """Manage agent swarms for multi-agent collaboration.

    Handles swarm lifecycle (spawn, query, eviction), role management, and
    delegates task execution to SwarmExecutor.
    """

    _MAX_SWARMS = 100

    def __init__(self, message_handler=None, custom_roles: dict[str, SwarmMember] | None = None,
                 tracker=None, team_builder=None, skill_store=None,
                 prompt_builder=None):
        from breadmind.core.swarm_executor import SwarmCoordinator

        self._message_handler = message_handler
        self._roles = build_default_roles(prompt_builder)
        if custom_roles:
            self._roles.update(custom_roles)
        self._coordinator = SwarmCoordinator(message_handler=message_handler)
        self._swarms: dict[str, SwarmResult] = {}
        self._lock = asyncio.Lock()
        self._bg_tasks: set[asyncio.Task] = set()
        self._tracker = tracker
        self._team_builder = team_builder
        self._skill_store = skill_store
        self._retriever = None

    def set_retriever(self, retriever):
        self._retriever = retriever

    def set_message_handler(self, handler):
        self._message_handler = handler
        self._coordinator._message_handler = handler

    def set_team_builder(self, team_builder):
        self._team_builder = team_builder

    def set_tracker(self, tracker):
        self._tracker = tracker

    def set_skill_store(self, skill_store):
        self._skill_store = skill_store

    # -- Swarm lifecycle --

    async def spawn_swarm(self, goal: str, roles: list[str] | None = None) -> SwarmResult:
        """Spawn a new swarm to achieve a goal."""
        swarm_id = str(uuid.uuid4())[:8]
        swarm = SwarmResult(id=swarm_id, goal=goal)

        async with self._lock:
            while len(self._swarms) >= self._MAX_SWARMS:
                evict_id = self._find_oldest_finished_swarm()
                if evict_id is not None:
                    del self._swarms[evict_id]
                else:
                    break
            self._swarms[swarm_id] = swarm

        task = asyncio.create_task(self._execute_swarm(swarm, roles))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return swarm

    def _find_oldest_finished_swarm(self) -> str | None:
        """Return the id of the oldest completed or failed swarm, or None."""
        oldest_id: str | None = None
        oldest_time: datetime | None = None
        for sid, sr in self._swarms.items():
            if sr.status in ("completed", "failed"):
                if oldest_time is None or sr.created_at < oldest_time:
                    oldest_time = sr.created_at
                    oldest_id = sid
        return oldest_id

    async def _execute_swarm(self, swarm: SwarmResult, roles: list[str] | None = None):
        """Delegate execution to SwarmExecutor."""
        from breadmind.core.swarm_executor import SwarmExecutor

        executor = SwarmExecutor(
            coordinator=self._coordinator,
            roles=self._roles,
            message_handler=self._message_handler,
            tracker=self._tracker,
            skill_store=self._skill_store,
            retriever=self._retriever,
        )
        await executor.execute(swarm, roles_filter=roles, team_builder=self._team_builder)

    # -- State queries --

    def get_swarm(self, swarm_id: str) -> dict | None:
        swarm = self._swarms.get(swarm_id)
        if not swarm:
            return None
        return {
            "id": swarm.id,
            "goal": swarm.goal,
            "status": swarm.status,
            "tasks": swarm.tasks,
            "final_result": swarm.final_result,
            "created_at": swarm.created_at.isoformat(),
            "completed_at": swarm.completed_at.isoformat() if swarm.completed_at else None,
            "error": swarm.error,
        }

    def list_swarms(self, limit: int = 20) -> list[dict]:
        swarms = sorted(self._swarms.values(), key=lambda s: s.created_at, reverse=True)[:limit]
        return [self.get_swarm(s.id) for s in swarms]

    def get_status(self) -> dict:
        statuses = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for s in self._swarms.values():
            statuses[s.status] = statuses.get(s.status, 0) + 1
        return {"total": len(self._swarms), **statuses}

    def get_available_roles(self) -> list[dict]:
        return [
            {"role": name, "description": member.description, "is_default": name in DEFAULT_ROLES}
            for name, member in self._roles.items()
        ]

    # -- Role management --

    def add_role(self, name: str, system_prompt: str, description: str = "", source: str = "manual"):
        self._roles[name] = SwarmMember(
            role=name, system_prompt=system_prompt,
            description=description or f"Custom role: {name}",
            source=source,
        )

    def remove_role(self, name: str) -> bool:
        if name not in self._roles:
            return False
        self._roles.pop(name)
        return True

    def update_role(self, name: str, system_prompt: str = "", description: str = ""):
        member = self._roles.get(name)
        if member:
            if system_prompt:
                member.system_prompt = system_prompt
            if description:
                member.description = description
        else:
            self.add_role(name, system_prompt, description)

    def export_roles(self) -> dict[str, dict]:
        """Export all roles as serializable dict for DB persistence."""
        return {
            name: {"system_prompt": m.system_prompt, "description": m.description, "source": m.source}
            for name, m in self._roles.items()
        }

    def import_roles(self, roles_data: dict[str, dict]):
        """Import roles from DB, replacing current set."""
        self._roles.clear()
        for name, data in roles_data.items():
            self._roles[name] = SwarmMember(
                role=name,
                system_prompt=data.get("system_prompt", ""),
                description=data.get("description", f"Role: {name}"),
                source=data.get("source", "manual"),
            )
