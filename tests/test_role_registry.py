from breadmind.core.role_registry import RoleRegistry, RoleDefinition


def test_get_builtin_role():
    reg = RoleRegistry()
    role = reg.get("k8s_diagnostician")
    assert role is not None
    assert role.domain == "k8s"
    assert role.task_type == "diagnostician"
    assert "pods_list" in role.dedicated_tools
    assert "shell_exec" in role.common_tools


def test_get_unknown_role_returns_none():
    reg = RoleRegistry()
    assert reg.get("nonexistent_role") is None


def test_list_roles():
    reg = RoleRegistry()
    roles = reg.list_roles()
    assert len(roles) >= 6
    assert any(r.name == "k8s_diagnostician" for r in roles)


def test_get_tools_for_role():
    reg = RoleRegistry()
    tools = reg.get_tools("k8s_diagnostician")
    assert "pods_list" in tools
    assert "shell_exec" in tools


def test_get_tools_unknown_role_returns_common_only():
    reg = RoleRegistry()
    tools = reg.get_tools("nonexistent")
    assert "shell_exec" in tools
    assert len(tools) > 0


def test_register_custom_role():
    reg = RoleRegistry()
    role = RoleDefinition(
        name="custom_checker", domain="custom", task_type="checker",
        system_prompt="You check custom things.", description="Custom checker",
        dedicated_tools=["custom_tool"], common_tools=["shell_exec"],
    )
    reg.register(role)
    assert reg.get("custom_checker") is not None


def test_difficulty_to_model():
    reg = RoleRegistry()
    assert reg.difficulty_to_model("low") == "haiku"
    assert reg.difficulty_to_model("medium") == "sonnet"
    assert reg.difficulty_to_model("high") == "opus"


# --- Additional coverage tests ---

def test_all_9_builtin_roles_present():
    reg = RoleRegistry()
    expected = {
        "k8s_diagnostician", "k8s_executor",
        "proxmox_diagnostician", "proxmox_executor",
        "openwrt_diagnostician", "openwrt_executor",
        "general_analyst", "security_analyst", "performance_analyst",
    }
    names = {r.name for r in reg.list_roles()}
    assert expected.issubset(names)


def test_remove_role():
    reg = RoleRegistry()
    assert reg.remove("general_analyst") is True
    assert reg.get("general_analyst") is None
    assert reg.remove("general_analyst") is False


def test_get_prompt_returns_system_prompt():
    reg = RoleRegistry()
    prompt = reg.get_prompt("k8s_diagnostician")
    assert len(prompt) > 0
    assert "Kubernetes" in prompt


def test_get_prompt_unknown_role_returns_empty():
    reg = RoleRegistry()
    assert reg.get_prompt("no_such_role") == ""


def test_list_role_summaries_contains_all_roles():
    reg = RoleRegistry()
    summary = reg.list_role_summaries()
    assert "k8s_diagnostician" in summary
    assert "proxmox_executor" in summary
    assert "security_analyst" in summary


def test_get_tools_deduplication():
    """Tools that appear in both dedicated and common lists should appear only once."""
    reg = RoleRegistry()
    # openwrt_executor has dedicated_tools that overlap with common_tools (shell_exec is in common)
    # but dedicated_tools don't actually overlap — create a role that does
    role = RoleDefinition(
        name="dedup_test", domain="test", task_type="tester",
        system_prompt="Test dedup.",
        dedicated_tools=["shell_exec", "custom_tool"],
        common_tools=["shell_exec", "file_read"],
    )
    reg.register(role)
    tools = reg.get_tools("dedup_test")
    assert tools.count("shell_exec") == 1


def test_difficulty_to_model_unknown_defaults_to_sonnet():
    reg = RoleRegistry()
    assert reg.difficulty_to_model("unknown_level") == "sonnet"
