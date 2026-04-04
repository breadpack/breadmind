from breadmind.plugins.v2_builtin.domains.infra.tools import K8S_TOOLS, PROXMOX_TOOLS, OPENWRT_TOOLS, ALL_INFRA_TOOLS
from breadmind.plugins.v2_builtin.domains.infra.roles import INFRA_ROLES
from breadmind.plugins.v2_builtin.domains.infra.plugin import InfraPlugin


def test_k8s_tools_defined():
    assert len(K8S_TOOLS) >= 8
    names = [t.name for t in K8S_TOOLS]
    assert "k8s_pods_list" in names
    assert "k8s_nodes_top" in names


def test_proxmox_tools_defined():
    assert len(PROXMOX_TOOLS) >= 5
    names = [t.name for t in PROXMOX_TOOLS]
    assert "proxmox_get_vms" in names


def test_openwrt_tools_defined():
    assert len(OPENWRT_TOOLS) >= 3
    names = [t.name for t in OPENWRT_TOOLS]
    assert "openwrt_network_status" in names


def test_all_tools_combined():
    assert len(ALL_INFRA_TOOLS) == len(K8S_TOOLS) + len(PROXMOX_TOOLS) + len(OPENWRT_TOOLS)


def test_infra_roles():
    assert "k8s_expert" in INFRA_ROLES
    assert "proxmox_expert" in INFRA_ROLES
    assert "openwrt_expert" in INFRA_ROLES
    assert "prompt" in INFRA_ROLES["k8s_expert"]
    assert "tools" in INFRA_ROLES["k8s_expert"]


def test_plugin_manifest():
    plugin = InfraPlugin()
    assert plugin.manifest.name == "infra"
    assert "infra_tools" in plugin.manifest.provides


def test_plugin_get_tools():
    tools = InfraPlugin.get_tools()
    assert len(tools) > 0


def test_plugin_get_roles():
    roles = InfraPlugin.get_roles()
    assert len(roles) == 3
