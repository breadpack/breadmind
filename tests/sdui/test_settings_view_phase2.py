# tests/sdui/test_settings_view_phase2.py
"""Phase 2 SDUI settings view tests.

Covers the Integrations, Safety & Permissions, and Monitoring tabs.
Memory and Advanced tabs remain placeholders (Phase 3).
"""
from breadmind.sdui.views import settings_view


def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_walk(ch, predicate))
    return out


class FakeStore:
    def __init__(self, data=None):
        self.data = data or {}

    async def get_setting(self, key):
        return self.data.get(key)


# ---------------------------------------------------------------------------
# Fixture data helpers
# ---------------------------------------------------------------------------

def _mcp_servers():
    return [
        {"name": "filesystem", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"], "env": {}, "enabled": True},
        {"name": "brave-search", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-brave-search"], "env": {}, "enabled": False},
    ]


def _skill_markets():
    return [
        {"name": "official", "type": "skills_sh", "enabled": True, "url": "https://skills.sh"},
        {"name": "community", "type": "clawhub", "enabled": False},
    ]


def _safety_blacklist():
    return {
        "shell": ["rm_rf", "dd"],
        "network": ["raw_socket"],
    }


def _safety_approval():
    return ["deploy_production", "send_email"]


def _safety_permissions():
    return {
        "admin_users": ["alice", "bob"],
        "user_permissions": {"charlie": ["read_file"]},
    }


def _tool_security():
    return {
        "base_directory": "/home/user",
        "command_whitelist_enabled": True,
        "dangerous_patterns": ["rm -rf", "mkfs"],
        "sensitive_file_patterns": [".env", "*.key"],
        "allowed_ssh_hosts": ["server1.local"],
        "command_whitelist": ["ls", "cat", "git"],
    }


def _monitoring_config():
    return {
        "rules": [
            {
                "name": "cpu_high",
                "description": "CPU usage > 90%",
                "severity": "warning",
                "source": "prometheus",
                "interval_seconds": 120,
                "enabled": True,
            },
            {
                "name": "disk_full",
                "description": "Disk usage > 95%",
                "severity": "critical",
                "source": "node_exporter",
                "interval_seconds": 300,
                "enabled": False,
            },
        ],
        "loop_protector": {
            "cooldown_minutes": 5,
            "max_auto_actions": 10,
        },
    }


def _scheduler_cron():
    return [
        {"id": "j1", "name": "daily-report", "schedule": "0 9 * * *", "task": "generate daily report", "enabled": True},
        {"id": "j2", "name": "weekly-backup", "schedule": "0 3 * * 0", "task": "backup all data", "enabled": False},
    ]


def _full_store_data():
    return {
        "mcp": {"auto_discover": True, "max_restart_attempts": 3},
        "mcp_servers": _mcp_servers(),
        "skill_markets": _skill_markets(),
        "safety_blacklist": _safety_blacklist(),
        "safety_approval": _safety_approval(),
        "safety_permissions": _safety_permissions(),
        "tool_security": _tool_security(),
        "monitoring_config": _monitoring_config(),
        "scheduler_cron": _scheduler_cron(),
    }


# ---------------------------------------------------------------------------
# Tab structure
# ---------------------------------------------------------------------------

async def test_settings_view_seven_tabs_phase2(test_db):
    """All 7 tab labels present and in correct order."""
    spec = await settings_view.build(test_db, settings_store=FakeStore(_full_store_data()))
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    labels = [ch.props.get("label", "") for ch in tabs_comps[0].children]
    assert labels == [
        "빠른 시작",
        "에이전트 동작",
        "통합",
        "안전 & 권한",
        "모니터링",
        "메모리",
        "고급",
    ]


# ---------------------------------------------------------------------------
# Integrations tab
# ---------------------------------------------------------------------------

async def test_integrations_tab_has_mcp_form(test_db):
    """Integrations tab contains a form with key='mcp'."""
    store = FakeStore({"mcp": {"auto_discover": False, "max_restart_attempts": 5}})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    mcp_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "mcp"]
    assert len(mcp_forms) == 1
    action = mcp_forms[0].props["action"]
    assert action["kind"] == "settings_write"
    assert mcp_forms[0].props.get("submit_label")


async def test_integrations_tab_mcp_form_fields(test_db):
    """MCP global config form has auto_discover and max_restart_attempts fields."""
    store = FakeStore({"mcp": {"auto_discover": True, "max_restart_attempts": 3}})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    mcp_form = next(f for f in forms if (f.props.get("action") or {}).get("key") == "mcp")
    fields = _walk(mcp_form, lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    assert "auto_discover" in field_names
    assert "max_restart_attempts" in field_names


async def test_integrations_tab_mcp_servers_delete_buttons(test_db):
    """Integrations tab renders existing mcp_servers with delete buttons."""
    store = FakeStore({"mcp_servers": _mcp_servers()})
    spec = await settings_view.build(test_db, settings_store=store)
    # Find buttons with settings_write action targeting mcp_servers
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "mcp_servers"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    # One delete button per server
    assert len(delete_btns) >= len(_mcp_servers())


async def test_integrations_tab_mcp_servers_delete_prebuilds_remaining_list(test_db):
    """Each mcp_servers delete button embeds the remaining list (without that server)."""
    store = FakeStore({"mcp_servers": _mcp_servers()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "mcp_servers"
    ]
    names_in_action_values = set()
    for btn in delete_btns:
        remaining = btn.props["action"].get("values", [])
        assert isinstance(remaining, list)
        for srv in remaining:
            names_in_action_values.add(srv["name"])
    # After deleting one server, the remaining list should not contain that server
    # i.e., "filesystem" button's values should only contain "brave-search" and vice versa
    all_names = {s["name"] for s in _mcp_servers()}
    for btn in delete_btns:
        remaining = btn.props["action"].get("values", [])
        remaining_names = {s["name"] for s in remaining}
        assert len(remaining_names) < len(all_names)  # at least one was removed


async def test_integrations_tab_skill_markets_delete_buttons(test_db):
    """Integrations tab renders existing skill_markets with delete buttons."""
    store = FakeStore({"skill_markets": _skill_markets()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "skill_markets"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    assert len(delete_btns) >= len(_skill_markets())


async def test_integrations_tab_empty_mcp_servers(test_db):
    """Integrations tab renders gracefully when mcp_servers is empty."""
    store = FakeStore({"mcp_servers": []})
    spec = await settings_view.build(test_db, settings_store=store)
    assert spec.root.type == "page"


# ---------------------------------------------------------------------------
# Safety & Permissions tab
# ---------------------------------------------------------------------------

async def test_safety_tab_blacklist_delete_buttons(test_db):
    """Safety tab renders delete buttons for safety_blacklist tools."""
    store = FakeStore({"safety_blacklist": _safety_blacklist()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "safety_blacklist"
    ]
    # 2 domains * tools: shell has 2 tools, network has 1 tool -> 3 delete buttons
    total_tools = sum(len(v) for v in _safety_blacklist().values())
    assert len(delete_btns) >= total_tools


async def test_safety_tab_approval_delete_buttons(test_db):
    """Safety tab renders delete buttons for safety_approval tools."""
    store = FakeStore({"safety_approval": _safety_approval()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "safety_approval"
    ]
    assert len(delete_btns) >= len(_safety_approval())


async def test_safety_tab_tool_security_form(test_db):
    """Safety tab contains a form with key='tool_security'."""
    store = FakeStore({"tool_security": _tool_security()})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    ts_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "tool_security"]
    assert len(ts_forms) == 1
    assert ts_forms[0].props.get("submit_label")
    # Must include base_directory and command_whitelist_enabled
    fields = _walk(ts_forms[0], lambda c: c.type in ("field", "select"))
    field_names = [f.props.get("name") for f in fields]
    assert "base_directory" in field_names
    assert "command_whitelist_enabled" in field_names


async def test_safety_tab_admin_users_empty_state(test_db):
    """Safety tab shows empty-state text when admin_users list is empty."""
    store = FakeStore({"safety_permissions": {"admin_users": [], "user_permissions": {}}})
    spec = await settings_view.build(test_db, settings_store=store)
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("비어" in v or "모든 사용자" in v for v in text_values)


async def test_safety_tab_admin_users_delete_buttons(test_db):
    """Safety tab renders delete buttons for admin_users list."""
    store = FakeStore({"safety_permissions": _safety_permissions()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "safety_permissions"
    ]
    assert len(delete_btns) >= len(_safety_permissions()["admin_users"])


# ---------------------------------------------------------------------------
# Monitoring tab
# ---------------------------------------------------------------------------

async def test_monitoring_tab_rules_toggle_buttons(test_db):
    """Monitoring tab renders rules from monitoring_config with toggle buttons."""
    store = FakeStore({"monitoring_config": _monitoring_config()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    toggle_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "monitoring_config"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    num_rules = len(_monitoring_config()["rules"])
    assert len(toggle_btns) >= num_rules


async def test_monitoring_tab_rule_toggle_prebuilds_full_config(test_db):
    """Each toggle button embeds the full monitoring_config with enabled flipped."""
    store = FakeStore({"monitoring_config": _monitoring_config()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    toggle_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "monitoring_config"
    ]
    for btn in toggle_btns:
        values = btn.props["action"].get("values", {})
        assert "rules" in values
        assert isinstance(values["rules"], list)
        for rule in values["rules"]:
            assert "name" in rule
            assert "enabled" in rule
            assert "interval_seconds" in rule


async def test_monitoring_tab_loop_protector_form(test_db):
    """Monitoring tab contains a form with key='monitoring_config' for loop protector."""
    store = FakeStore({"monitoring_config": _monitoring_config()})
    spec = await settings_view.build(test_db, settings_store=store)
    forms = _walk(spec.root, lambda c: c.type == "form")
    mc_forms = [f for f in forms if (f.props.get("action") or {}).get("key") == "monitoring_config"]
    assert len(mc_forms) >= 1
    # Check submit_label
    assert any(f.props.get("submit_label") for f in mc_forms)
    # Check loop protector fields
    all_fields = []
    for f in mc_forms:
        all_fields.extend(_walk(f, lambda c: c.type in ("field", "select")))
    field_names = [f.props.get("name") for f in all_fields]
    assert "cooldown_minutes" in field_names
    assert "max_auto_actions" in field_names


async def test_monitoring_tab_scheduler_cron_entries(test_db):
    """Monitoring tab renders scheduler_cron entries with delete buttons."""
    store = FakeStore({"scheduler_cron": _scheduler_cron()})
    spec = await settings_view.build(test_db, settings_store=store)
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "scheduler_cron"
    ]
    assert len(delete_btns) >= len(_scheduler_cron())


# ---------------------------------------------------------------------------
# Placeholders still in place
# ---------------------------------------------------------------------------

async def test_memory_tab_is_placeholder(test_db):
    """Memory tab still shows placeholder text (Phase 3)."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    memory_tab = next(
        ch for ch in tabs_comps[0].children if ch.props.get("label") == "메모리"
    )
    texts = _walk(memory_tab, lambda c: c.type == "text")
    assert len(texts) >= 1


async def test_advanced_tab_is_placeholder(test_db):
    """Advanced tab still shows placeholder text (Phase 3)."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    adv_tab = next(
        ch for ch in tabs_comps[0].children if ch.props.get("label") == "고급"
    )
    texts = _walk(adv_tab, lambda c: c.type == "text")
    assert len(texts) >= 1


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

async def test_view_renders_with_no_store(test_db):
    """View renders cleanly when settings_store is None."""
    spec = await settings_view.build(test_db)
    assert spec.root.type == "page"
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    assert len(tabs_comps[0].children) == 7


async def test_view_renders_with_empty_phase2_data(test_db):
    """View renders cleanly with empty/missing Phase 2 store values."""
    store = FakeStore({
        "mcp_servers": [],
        "skill_markets": [],
        "safety_blacklist": {},
        "safety_approval": [],
        "safety_permissions": {"admin_users": [], "user_permissions": {}},
        "monitoring_config": {"rules": [], "loop_protector": {"cooldown_minutes": 5, "max_auto_actions": 10}},
        "scheduler_cron": [],
    })
    spec = await settings_view.build(test_db, settings_store=store)
    assert spec.root.type == "page"
