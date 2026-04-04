"""인프라 도메인 도구 정의."""
from breadmind.core.protocols import ToolDefinition

K8S_TOOLS = [
    ToolDefinition(name="k8s_pods_list", description="List Kubernetes pods", parameters={"type": "object", "properties": {"namespace": {"type": "string"}}}),
    ToolDefinition(name="k8s_pods_get", description="Get Kubernetes pod details", parameters={"type": "object", "properties": {"name": {"type": "string"}, "namespace": {"type": "string"}}}),
    ToolDefinition(name="k8s_pods_log", description="Get pod logs", parameters={"type": "object", "properties": {"name": {"type": "string"}, "namespace": {"type": "string"}}}),
    ToolDefinition(name="k8s_pods_delete", description="Delete a pod", parameters={"type": "object", "properties": {"name": {"type": "string"}, "namespace": {"type": "string"}}}),
    ToolDefinition(name="k8s_nodes_top", description="Show node resource usage", parameters={"type": "object", "properties": {}}),
    ToolDefinition(name="k8s_pods_top", description="Show pod resource usage", parameters={"type": "object", "properties": {"namespace": {"type": "string"}}}),
    ToolDefinition(name="k8s_events_list", description="List cluster events", parameters={"type": "object", "properties": {"namespace": {"type": "string"}}}),
    ToolDefinition(name="k8s_resources_list", description="List Kubernetes resources", parameters={"type": "object", "properties": {"kind": {"type": "string"}, "namespace": {"type": "string"}}}),
    ToolDefinition(name="k8s_resources_get", description="Get a Kubernetes resource", parameters={"type": "object", "properties": {"kind": {"type": "string"}, "name": {"type": "string"}}}),
    ToolDefinition(name="k8s_resources_scale", description="Scale a deployment", parameters={"type": "object", "properties": {"name": {"type": "string"}, "replicas": {"type": "integer"}}}),
]

PROXMOX_TOOLS = [
    ToolDefinition(name="proxmox_get_vms", description="List Proxmox VMs", parameters={"type": "object", "properties": {}}),
    ToolDefinition(name="proxmox_get_vm_status", description="Get VM status", parameters={"type": "object", "properties": {"vmid": {"type": "integer"}}}),
    ToolDefinition(name="proxmox_start_vm", description="Start a VM", parameters={"type": "object", "properties": {"vmid": {"type": "integer"}}}),
    ToolDefinition(name="proxmox_stop_vm", description="Stop a VM", parameters={"type": "object", "properties": {"vmid": {"type": "integer"}}}),
    ToolDefinition(name="proxmox_get_nodes", description="List Proxmox nodes", parameters={"type": "object", "properties": {}}),
    ToolDefinition(name="proxmox_get_storage", description="Get storage info", parameters={"type": "object", "properties": {}}),
]

OPENWRT_TOOLS = [
    ToolDefinition(name="openwrt_network_status", description="Get OpenWrt network status", parameters={"type": "object", "properties": {}}),
    ToolDefinition(name="openwrt_system_status", description="Get OpenWrt system status", parameters={"type": "object", "properties": {}}),
    ToolDefinition(name="openwrt_read_log", description="Read OpenWrt logs", parameters={"type": "object", "properties": {"lines": {"type": "integer"}}}),
]

ALL_INFRA_TOOLS = K8S_TOOLS + PROXMOX_TOOLS + OPENWRT_TOOLS
