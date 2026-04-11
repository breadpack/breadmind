# tests/sdui/test_settings_view_phase4.py
"""Phase 4 SDUI settings view tests.

Covers the item-add forms for:
  - MCP 서버 추가
  - 스킬 마켓 추가
  - 차단 도구 추가
  - 승인 도구 추가
  - 관리자 사용자 추가
  - 스케줄러 크론 추가
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
# Helpers
# ---------------------------------------------------------------------------

def _append_forms(spec):
    """Return all forms with kind == 'settings_append'."""
    forms = _walk(spec.root, lambda c: c.type == "form")
    return [f for f in forms if (f.props.get("action") or {}).get("kind") == "settings_append"]


def _form_for_key(spec, key):
    for f in _append_forms(spec):
        if (f.props.get("action") or {}).get("key") == key:
            return f
    return None


def _field_names(form):
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    return [f.props.get("name") for f in fields]


# ---------------------------------------------------------------------------
# 1. MCP 서버 추가
# ---------------------------------------------------------------------------

async def test_mcp_servers_add_form_exists(test_db):
    """_mcp_servers_card has an add form with key='mcp_servers'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "mcp_servers")
    assert form is not None, "No settings_append form found for mcp_servers"
    assert form.props.get("submit_label"), "Form must have submit_label"


async def test_mcp_servers_add_form_id(test_db):
    """MCP add form has id 'int-mcp-add-form'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "mcp_servers")
    assert form is not None
    assert form.id == "int-mcp-add-form"


async def test_mcp_servers_add_form_fields(test_db):
    """MCP add form has 'name' and 'command' fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "mcp_servers")
    assert form is not None
    names = _field_names(form)
    assert "name" in names
    assert "command" in names


async def test_mcp_servers_delete_buttons_still_present(test_db):
    """Existing delete buttons for mcp_servers are still rendered after Phase 4."""
    servers = [
        {"name": "fs", "command": "npx", "args": [], "env": {}, "enabled": True},
        {"name": "brave", "command": "npx", "args": [], "env": {}, "enabled": True},
    ]
    spec = await settings_view.build(test_db, settings_store=FakeStore({"mcp_servers": servers}))
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "mcp_servers"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    assert len(delete_btns) >= len(servers)


# ---------------------------------------------------------------------------
# 2. 스킬 마켓 추가
# ---------------------------------------------------------------------------

async def test_skill_markets_add_form_exists(test_db):
    """_skill_markets_card has an add form with key='skill_markets'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "skill_markets")
    assert form is not None, "No settings_append form found for skill_markets"
    assert form.props.get("submit_label")


async def test_skill_markets_add_form_id(test_db):
    """Skill markets add form has id 'int-market-add-form'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "skill_markets")
    assert form is not None
    assert form.id == "int-market-add-form"


async def test_skill_markets_add_form_fields(test_db):
    """Skill markets add form has name, type, url, enabled fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "skill_markets")
    assert form is not None
    names = _field_names(form)
    assert "name" in names
    assert "type" in names
    assert "url" in names
    assert "enabled" in names


async def test_skill_markets_add_form_type_select_options(test_db):
    """Skill markets add form 'type' select has the 4 required options."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "skill_markets")
    assert form is not None
    selects = _walk(form, lambda c: c.type == "select" and c.props.get("name") == "type")
    assert len(selects) == 1, "Expected exactly one 'type' select"
    option_values = [o["value"] for o in selects[0].props.get("options", [])]
    assert "skills_sh" in option_values
    assert "skillsmp" in option_values
    assert "clawhub" in option_values
    assert "mcp_registry" in option_values


async def test_skill_markets_add_form_enabled_select(test_db):
    """Skill markets add form 'enabled' select defaults to 'true'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "skill_markets")
    assert form is not None
    selects = _walk(form, lambda c: c.type == "select" and c.props.get("name") == "enabled")
    assert len(selects) == 1
    assert selects[0].props.get("value") == "true"


# ---------------------------------------------------------------------------
# 3. 차단 도구 추가
# ---------------------------------------------------------------------------

async def test_blacklist_add_form_exists(test_db):
    """_blacklist_card has an add form with key='safety_blacklist'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_blacklist")
    assert form is not None, "No settings_append form found for safety_blacklist"
    assert form.props.get("submit_label")


async def test_blacklist_add_form_id(test_db):
    """Blacklist add form has id 'safety-blacklist-add-form'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_blacklist")
    assert form is not None
    assert form.id == "safety-blacklist-add-form"


async def test_blacklist_add_form_fields(test_db):
    """Blacklist add form has 'domain' and 'tool' fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_blacklist")
    assert form is not None
    names = _field_names(form)
    assert "domain" in names
    assert "tool" in names


async def test_blacklist_delete_buttons_still_present(test_db):
    """Existing delete buttons for safety_blacklist are still rendered."""
    bl = {"shell": ["rm_rf", "dd"], "network": ["raw_socket"]}
    spec = await settings_view.build(test_db, settings_store=FakeStore({"safety_blacklist": bl}))
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "safety_blacklist"
    ]
    total_tools = sum(len(v) for v in bl.values())
    assert len(delete_btns) >= total_tools


# ---------------------------------------------------------------------------
# 4. 승인 도구 추가
# ---------------------------------------------------------------------------

async def test_approval_add_form_exists(test_db):
    """_approval_card has an add form with key='safety_approval'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_approval")
    assert form is not None, "No settings_append form found for safety_approval"
    assert form.props.get("submit_label")


async def test_approval_add_form_id(test_db):
    """Approval add form has id 'safety-approval-add-form'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_approval")
    assert form is not None
    assert form.id == "safety-approval-add-form"


async def test_approval_add_form_fields(test_db):
    """Approval add form has a 'tool' field."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_approval")
    assert form is not None
    names = _field_names(form)
    assert "tool" in names


async def test_approval_delete_buttons_still_present(test_db):
    """Existing delete buttons for safety_approval are still rendered."""
    approval = ["deploy_production", "send_email"]
    spec = await settings_view.build(test_db, settings_store=FakeStore({"safety_approval": approval}))
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "safety_approval"
    ]
    assert len(delete_btns) >= len(approval)


# ---------------------------------------------------------------------------
# 5. 관리자 사용자 추가
# ---------------------------------------------------------------------------

async def test_admin_users_add_form_exists(test_db):
    """_permissions_card has an add form with key='safety_permissions_admin_users'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_permissions_admin_users")
    assert form is not None, "No settings_append form found for safety_permissions_admin_users"
    assert form.props.get("submit_label")


async def test_admin_users_add_form_id(test_db):
    """Admin users add form has id 'safety-admin-add-form'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_permissions_admin_users")
    assert form is not None
    assert form.id == "safety-admin-add-form"


async def test_admin_users_add_form_fields(test_db):
    """Admin users add form has a 'user' field."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "safety_permissions_admin_users")
    assert form is not None
    names = _field_names(form)
    assert "user" in names


async def test_admin_users_delete_buttons_still_present(test_db):
    """Existing delete buttons for safety_permissions are still rendered."""
    perms = {"admin_users": ["alice", "bob"], "user_permissions": {}}
    spec = await settings_view.build(test_db, settings_store=FakeStore({"safety_permissions": perms}))
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "safety_permissions"
    ]
    assert len(delete_btns) >= len(perms["admin_users"])


# ---------------------------------------------------------------------------
# 6. 스케줄러 크론 추가
# ---------------------------------------------------------------------------

async def test_scheduler_cron_add_form_exists(test_db):
    """_scheduler_cron_card has an add form with key='scheduler_cron'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "scheduler_cron")
    assert form is not None, "No settings_append form found for scheduler_cron"
    assert form.props.get("submit_label")


async def test_scheduler_cron_add_form_id(test_db):
    """Scheduler cron add form has id 'mon-cron-add-form'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "scheduler_cron")
    assert form is not None
    assert form.id == "mon-cron-add-form"


async def test_scheduler_cron_add_form_fields(test_db):
    """Scheduler cron add form has name, schedule, task, enabled fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "scheduler_cron")
    assert form is not None
    names = _field_names(form)
    assert "name" in names
    assert "schedule" in names
    assert "task" in names
    assert "enabled" in names


async def test_scheduler_cron_add_form_enabled_select(test_db):
    """Scheduler cron add form 'enabled' select defaults to 'true'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "scheduler_cron")
    assert form is not None
    selects = _walk(form, lambda c: c.type == "select" and c.props.get("name") == "enabled")
    assert len(selects) == 1
    assert selects[0].props.get("value") == "true"


async def test_scheduler_cron_delete_buttons_still_present(test_db):
    """Existing delete buttons for scheduler_cron are still rendered."""
    crons = [
        {"id": "j1", "name": "daily", "schedule": "0 9 * * *", "task": "report", "enabled": True},
        {"id": "j2", "name": "weekly", "schedule": "0 3 * * 0", "task": "backup", "enabled": False},
    ]
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": crons}))
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "scheduler_cron"
    ]
    assert len(delete_btns) >= len(crons)


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

async def test_view_renders_with_no_store_phase4(test_db):
    """View renders cleanly with no settings_store (Phase 4 forms still appear)."""
    spec = await settings_view.build(test_db)
    assert spec.root.type == "page"
    # All 6 append forms must exist even when store is empty
    keys = [
        "mcp_servers",
        "skill_markets",
        "safety_blacklist",
        "safety_approval",
        "safety_permissions_admin_users",
        "scheduler_cron",
    ]
    for key in keys:
        form = _form_for_key(spec, key)
        assert form is not None, f"Missing add form for key '{key}' when store is None"


async def test_all_six_add_forms_present(test_db):
    """Exactly 6 settings_append forms are present in the full view."""
    from tests.sdui.test_settings_view_phase2 import _full_store_data
    spec = await settings_view.build(test_db, settings_store=FakeStore(_full_store_data()))
    forms = _append_forms(spec)
    keys = {(f.props.get("action") or {}).get("key") for f in forms}
    expected = {
        "mcp_servers",
        "skill_markets",
        "safety_blacklist",
        "safety_approval",
        "safety_permissions_admin_users",
        "scheduler_cron",
    }
    assert expected == keys, f"Unexpected append form keys: {keys - expected!r}, missing: {expected - keys!r}"
