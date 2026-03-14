from breadmind.monitoring.engine import MonitoringEvent, MonitoringRule

def _check_pod_crash(state: dict, prev: dict | None) -> list[MonitoringEvent]:
    """Check for pod CrashLoopBackOff. State comes from K8s MCP tool."""
    events = []
    for pod in state.get("pods", []):
        status = pod.get("status", "")
        if status == "CrashLoopBackOff":
            events.append(MonitoringEvent(
                source="k8s",
                target=f"pod:{pod.get('name', 'unknown')}",
                severity="critical",
                condition="CrashLoopBackOff",
                details={"namespace": pod.get("namespace", "default"), "restarts": pod.get("restarts", 0)},
            ))
    return events

def _check_node_not_ready(state: dict, prev: dict | None) -> list[MonitoringEvent]:
    events = []
    for node in state.get("nodes", []):
        ready = node.get("ready", True)
        if not ready:
            events.append(MonitoringEvent(
                source="k8s",
                target=f"node:{node.get('name', 'unknown')}",
                severity="critical",
                condition="NotReady",
                details=node,
            ))
    return events

def _check_memory_high(state: dict, prev: dict | None) -> list[MonitoringEvent]:
    events = []
    for host in state.get("hosts", []):
        mem_pct = host.get("memory_percent", 0)
        if mem_pct > 90:
            events.append(MonitoringEvent(
                source=host.get("source", "system"),
                target=f"host:{host.get('name', 'unknown')}",
                severity="warning",
                condition="memory_high",
                details={"memory_percent": mem_pct},
            ))
    return events

def _check_vm_unexpected_stop(state: dict, prev: dict | None) -> list[MonitoringEvent]:
    events = []
    if prev is None:
        return events
    prev_vms = {vm.get("vmid"): vm for vm in prev.get("vms", [])}
    for vm in state.get("vms", []):
        vmid = vm.get("vmid")
        if vmid in prev_vms:
            was_running = prev_vms[vmid].get("status") == "running"
            now_stopped = vm.get("status") == "stopped"
            if was_running and now_stopped:
                events.append(MonitoringEvent(
                    source="proxmox",
                    target=f"vm:{vmid}",
                    severity="critical",
                    condition="unexpected_stop",
                    details={"name": vm.get("name", ""), "vmid": vmid},
                ))
    return events

def _check_wan_down(state: dict, prev: dict | None) -> list[MonitoringEvent]:
    events = []
    for iface in state.get("interfaces", []):
        if iface.get("name") == "wan" and iface.get("status") != "up":
            events.append(MonitoringEvent(
                source="openwrt",
                target="interface:wan",
                severity="critical",
                condition="wan_down",
                details=iface,
            ))
    return events

# Default rules
DEFAULT_RULES = [
    MonitoringRule(name="k8s_pod_crash", source="k8s", condition_fn=_check_pod_crash, interval_seconds=60, severity="critical", description="Detect pods in CrashLoopBackOff state"),
    MonitoringRule(name="k8s_node_not_ready", source="k8s", condition_fn=_check_node_not_ready, interval_seconds=300, severity="critical", description="Detect nodes in NotReady state"),
    MonitoringRule(name="memory_high", source="system", condition_fn=_check_memory_high, interval_seconds=300, severity="warning", description="Detect hosts with memory usage above 90%"),
    MonitoringRule(name="pve_vm_unexpected_stop", source="proxmox", condition_fn=_check_vm_unexpected_stop, interval_seconds=300, severity="critical", description="Detect VMs that stopped unexpectedly"),
    MonitoringRule(name="owrt_wan_down", source="openwrt", condition_fn=_check_wan_down, interval_seconds=300, severity="critical", description="Detect WAN interface down"),
]
