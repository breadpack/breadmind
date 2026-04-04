"""인프라 도메인 역할 정의."""

INFRA_ROLES = {
    "k8s_expert": {
        "description": "Kubernetes cluster expert",
        "prompt": (
            "You are a Kubernetes expert. Diagnose cluster issues, manage deployments, "
            "and optimize resource usage. Use K8s tools for investigation and action."
        ),
        "tools": ["k8s_pods_list", "k8s_pods_get", "k8s_pods_log", "k8s_nodes_top",
                   "k8s_pods_top", "k8s_events_list", "k8s_resources_list", "k8s_resources_get"],
    },
    "proxmox_expert": {
        "description": "Proxmox virtualization expert",
        "prompt": (
            "You are a Proxmox expert. Manage VMs, LXC containers, storage, and backups. "
            "Use Proxmox tools for monitoring and operations."
        ),
        "tools": ["proxmox_get_vms", "proxmox_get_vm_status", "proxmox_start_vm",
                   "proxmox_stop_vm", "proxmox_get_nodes", "proxmox_get_storage"],
    },
    "openwrt_expert": {
        "description": "OpenWrt network expert",
        "prompt": (
            "You are an OpenWrt expert. Manage network interfaces, firewall rules, "
            "DHCP, and system health."
        ),
        "tools": ["openwrt_network_status", "openwrt_system_status", "openwrt_read_log"],
    },
}
