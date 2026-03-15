import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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


class SwarmCoordinator:
    """LLM-based coordinator that decomposes goals into tasks and aggregates results."""

    def __init__(self, message_handler=None):
        self._message_handler = message_handler

    async def decompose(self, goal: str) -> list[SwarmTask]:
        """Use LLM to decompose a goal into subtasks with role assignments."""
        decompose_prompt = (
            f"Decompose this goal into 2-5 concrete subtasks. For each task, specify which expert role should handle it.\n\n"
            f"Available roles: {', '.join(DEFAULT_ROLES.keys())}\n\n"
            f"Goal: {goal}\n\n"
            f"Respond in this exact format (one task per line):\n"
            f"TASK|<role>|<description>|<depends_on_task_numbers_comma_separated_or_none>\n\n"
            f"Example:\n"
            f"TASK|k8s_expert|Check pod health and resource usage|none\n"
            f"TASK|proxmox_expert|Check VM resource usage|none\n"
            f"TASK|performance_analyst|Compare and analyze both results|1,2\n\n"
            f"Output ONLY the TASK lines, no other text."
        )

        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    response = await self._message_handler(
                        decompose_prompt, user="swarm_coordinator", channel="swarm:decompose"
                    )
                else:
                    response = self._message_handler(
                        decompose_prompt, user="swarm_coordinator", channel="swarm:decompose"
                    )
            except Exception as e:
                logger.error(f"Failed to decompose goal: {e}")
                # Fallback: single general task
                return [SwarmTask(id="t1", description=goal, role="general")]
        else:
            return [SwarmTask(id="t1", description=goal, role="general")]

        return self._parse_tasks(str(response))

    def _parse_tasks(self, response: str) -> list[SwarmTask]:
        """Parse LLM response into SwarmTasks."""
        tasks: list[SwarmTask] = []
        task_num = 0
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line.startswith("TASK|"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            task_num += 1
            role = parts[1].strip()
            description = parts[2].strip()
            depends_str = parts[3].strip() if len(parts) > 3 else "none"

            depends_on = []
            if depends_str.lower() != "none":
                for dep in depends_str.split(","):
                    dep = dep.strip()
                    if dep.isdigit():
                        depends_on.append(f"t{dep}")

            if role not in DEFAULT_ROLES:
                role = "general"

            tasks.append(SwarmTask(
                id=f"t{task_num}",
                description=description,
                role=role,
                depends_on=depends_on,
            ))

        if not tasks:
            tasks.append(SwarmTask(id="t1", description=response, role="general"))

        return tasks

    async def aggregate(self, goal: str, results: dict[str, str], task_roles: dict[str, str] | None = None) -> str:
        """Aggregate results from multiple tasks into a final answer."""
        aggregate_prompt = (
            f"You are aggregating results from multiple expert agents.\n\n"
            f"Original goal: {goal}\n\n"
            f"Results from each subtask:\n"
        )
        for task_id, result in results.items():
            role_label = f" (role: {task_roles[task_id]})" if task_roles and task_id in task_roles else ""
            aggregate_prompt += f"\n--- {task_id}{role_label} ---\n{result}\n"

        aggregate_prompt += (
            "\nProvide a comprehensive, unified analysis using the following structure:\n\n"
            "## Executive Summary\n"
            "A 2-3 sentence high-level overview of the overall infrastructure state.\n\n"
            "## Key Findings\n"
            "Group findings by severity. For each finding, include which role/agent reported it.\n\n"
            "### Critical\n"
            "- [role] Finding description and impact\n\n"
            "### Warning\n"
            "- [role] Finding description and potential risk\n\n"
            "### OK\n"
            "- [role] Verified healthy items (brief)\n\n"
            "## Recommended Actions\n"
            "Numbered list of prioritized actions, most urgent first.\n"
        )

        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    return await self._message_handler(
                        aggregate_prompt, user="swarm_coordinator", channel="swarm:aggregate"
                    )
                else:
                    return self._message_handler(
                        aggregate_prompt, user="swarm_coordinator", channel="swarm:aggregate"
                    )
            except Exception as e:
                logger.error(f"Failed to aggregate results: {e}")
                # Fallback: concatenate results
                return "\n\n".join(f"[{tid}] {r}" for tid, r in results.items())
        else:
            return "\n\n".join(f"[{tid}] {r}" for tid, r in results.items())


class SwarmManager:
    """Manage agent swarms for multi-agent collaboration."""

    _MAX_SWARMS = 100

    def __init__(self, message_handler=None, custom_roles: dict[str, SwarmMember] | None = None):
        self._message_handler = message_handler
        self._coordinator = SwarmCoordinator(message_handler=message_handler)
        self._swarms: dict[str, SwarmResult] = {}
        self._roles = {**DEFAULT_ROLES}
        if custom_roles:
            self._roles.update(custom_roles)
        self._lock = asyncio.Lock()
        self._bg_tasks: set[asyncio.Task] = set()

    def set_message_handler(self, handler):
        self._message_handler = handler
        self._coordinator._message_handler = handler

    async def spawn_swarm(self, goal: str, roles: list[str] | None = None) -> SwarmResult:
        """Spawn a new swarm to achieve a goal."""
        swarm_id = str(uuid.uuid4())[:8]
        swarm = SwarmResult(id=swarm_id, goal=goal)

        async with self._lock:
            # Evict oldest completed/failed swarms if at capacity
            while len(self._swarms) >= self._MAX_SWARMS:
                evict_id = self._find_oldest_finished_swarm()
                if evict_id is not None:
                    del self._swarms[evict_id]
                else:
                    # All swarms are still running — allow overshoot rather than block
                    break
            self._swarms[swarm_id] = swarm

        # Start execution in background and track the task
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
        """Execute a swarm: decompose -> dispatch -> aggregate."""
        swarm.status = "running"
        try:
            # Phase 1: Decompose goal into tasks
            tasks = await self._coordinator.decompose(swarm.goal)

            # Filter by requested roles if specified
            if roles:
                tasks = [t for t in tasks if t.role in roles] or tasks

            context = SwarmContext()
            for task in tasks:
                context.task_graph[task.id] = task
                swarm.tasks.append({
                    "id": task.id, "description": task.description,
                    "role": task.role, "depends_on": task.depends_on,
                    "status": task.status,
                })

            # Phase 2: Execute tasks respecting dependencies
            results: dict[str, str] = {}
            task_roles: dict[str, str] = {t.id: t.role for t in tasks}
            completed_ids: set[str] = set()

            while len(completed_ids) < len(tasks):
                # Find tasks ready to run (dependencies met)
                ready = [
                    t for t in tasks
                    if t.id not in completed_ids
                    and t.status == "pending"
                    and all(d in completed_ids for d in t.depends_on)
                ]

                if not ready:
                    # Check for stuck tasks (dependencies that failed)
                    stuck = [t for t in tasks if t.id not in completed_ids and t.status == "pending"]
                    if stuck:
                        for t in stuck:
                            t.status = "failed"
                            t.error = "Dependencies not met"
                            completed_ids.add(t.id)
                        break
                    break

                # Execute ready tasks in parallel
                async def run_task(task: SwarmTask) -> None:
                    task.status = "running"
                    self._update_swarm_task(swarm, task)
                    try:
                        member = self._roles.get(task.role, DEFAULT_ROLES["general"])
                        # Build task prompt with context from dependencies
                        prompt = f"[Role: {member.role}]\n{member.system_prompt}\n\nTask: {task.description}"
                        if task.depends_on:
                            prompt += "\n\nPrevious results:"
                            for dep_id in task.depends_on:
                                if dep_id in results:
                                    prompt += f"\n--- From {dep_id} ---\n{results[dep_id][:2000]}"

                        if self._message_handler:
                            if asyncio.iscoroutinefunction(self._message_handler):
                                result = await self._message_handler(
                                    prompt, user=f"swarm:{task.role}",
                                    channel=f"swarm:{swarm.id}:{task.id}"
                                )
                            else:
                                result = self._message_handler(
                                    prompt, user=f"swarm:{task.role}",
                                    channel=f"swarm:{swarm.id}:{task.id}"
                                )
                        else:
                            result = f"No message handler available for task: {task.description}"

                        task.result = str(result)
                        task.status = "completed"
                        results[task.id] = task.result
                    except Exception as e:
                        task.error = str(e)
                        task.status = "failed"
                        results[task.id] = f"Error: {e}"
                        logger.error(f"Swarm task {task.id} failed: {e}")
                    finally:
                        completed_ids.add(task.id)
                        self._update_swarm_task(swarm, task)

                await asyncio.gather(*[run_task(t) for t in ready])

            # Phase 3: Aggregate results
            if results:
                swarm.final_result = await self._coordinator.aggregate(
                    swarm.goal, results, task_roles=task_roles
                )
            else:
                swarm.final_result = "No tasks completed successfully."

            swarm.status = "completed"

        except Exception as e:
            swarm.status = "failed"
            swarm.error = str(e)
            logger.error(f"Swarm {swarm.id} failed: {e}")
        finally:
            swarm.completed_at = datetime.now(timezone.utc)

    def _update_swarm_task(self, swarm: SwarmResult, task: SwarmTask):
        """Update task status in swarm result."""
        for t in swarm.tasks:
            if t["id"] == task.id:
                t["status"] = task.status
                if task.result:
                    t["result"] = task.result[:500]  # Truncate for API
                if task.error:
                    t["error"] = task.error
                break

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
            {"role": name, "description": member.description}
            for name, member in self._roles.items()
        ]
