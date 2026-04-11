"""Phase 6 SDUI settings view tests.

Covers:
  - MCP add form has 5 fields (name, command, args, env, enabled)
  - Each existing server has an inline edit form with the right action
  - Edit form prefills args/env from existing data (joined by newlines)
  - Edit form has name field marked read_only or disabled
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


_SERVERS = [
    {
        "name": "github",
        "command": "npx",
        "args": ["-y", "github-mcp"],
        "env": {"TOKEN": "abc", "HOST": "localhost"},
        "enabled": True,
    },
    {
        "name": "brave",
        "command": "node",
        "args": [],
        "env": {},
        "enabled": False,
    },
]


def _append_forms(spec):
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


def _update_item_forms(spec):
    forms = _walk(spec.root, lambda c: c.type == "form")
    return [f for f in forms if (f.props.get("action") or {}).get("kind") == "settings_update_item"]


def _edit_form_for_server(spec, server_name):
    for f in _update_item_forms(spec):
        action = f.props.get("action") or {}
        if action.get("key") == "mcp_servers" and action.get("match_value") == server_name:
            return f
    return None


# ---------------------------------------------------------------------------
# Add form has all 5 fields
# ---------------------------------------------------------------------------

async def test_mcp_add_form_has_five_fields(test_db):
    """MCP add form now has name, command, args, env, enabled fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "mcp_servers")
    assert form is not None
    names = _field_names(form)
    assert "name" in names
    assert "command" in names
    assert "args" in names
    assert "env" in names
    assert "enabled" in names


async def test_mcp_add_form_enabled_select_defaults_true(test_db):
    """MCP add form 'enabled' select defaults to 'true'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "mcp_servers")
    assert form is not None
    selects = _walk(form, lambda c: c.type == "select" and c.props.get("name") == "enabled")
    assert len(selects) == 1
    assert selects[0].props.get("value") == "true"


async def test_mcp_add_form_args_is_multiline(test_db):
    """MCP add form 'args' field has multiline=True."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "mcp_servers")
    assert form is not None
    args_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "args")
    assert len(args_fields) == 1
    assert args_fields[0].props.get("multiline") is True


async def test_mcp_add_form_env_is_multiline(test_db):
    """MCP add form 'env' field has multiline=True."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    form = _form_for_key(spec, "mcp_servers")
    assert form is not None
    env_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "env")
    assert len(env_fields) == 1
    assert env_fields[0].props.get("multiline") is True


# ---------------------------------------------------------------------------
# Inline edit form per server
# ---------------------------------------------------------------------------

async def test_each_server_has_inline_edit_form(test_db):
    """Each existing mcp_server entry has an inline edit form when expanded."""
    for srv in _SERVERS:
        spec = await settings_view.build(
            test_db,
            settings_store=FakeStore({"mcp_servers": _SERVERS}),
            expand_server=srv["name"],
        )
        form = _edit_form_for_server(spec, srv["name"])
        assert form is not None, f"No inline edit form found for server '{srv['name']}'"


async def test_edit_form_action_has_match_field(test_db):
    """Edit form action has match_field='name'."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    form = _edit_form_for_server(spec, "github")
    assert form is not None
    action = form.props.get("action") or {}
    assert action.get("match_field") == "name"
    assert action.get("match_value") == "github"


async def test_edit_form_has_required_fields(test_db):
    """Each edit form has name, command, args, env, enabled fields."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    form = _edit_form_for_server(spec, "github")
    assert form is not None
    names = _field_names(form)
    assert "name" in names
    assert "command" in names
    assert "args" in names
    assert "env" in names
    assert "enabled" in names


async def test_edit_form_args_prefilled(test_db):
    """Edit form prefills args from existing list joined by newlines."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    form = _edit_form_for_server(spec, "github")
    assert form is not None
    args_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "args")
    assert len(args_fields) == 1
    assert args_fields[0].props.get("value") == "-y\ngithub-mcp"


async def test_edit_form_env_prefilled(test_db):
    """Edit form prefills env from existing dict joined as KEY=VALUE lines."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    form = _edit_form_for_server(spec, "github")
    assert form is not None
    env_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "env")
    assert len(env_fields) == 1
    env_value = env_fields[0].props.get("value", "")
    # Must contain both key=value pairs (order may vary)
    lines = set(env_value.strip().splitlines())
    assert "TOKEN=abc" in lines
    assert "HOST=localhost" in lines


async def test_edit_form_enabled_select_prefilled(test_db):
    """Edit form 'enabled' select is prefilled from existing server data."""
    # github is enabled=True
    spec_github = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    form_github = _edit_form_for_server(spec_github, "github")
    assert form_github is not None
    enabled_selects_g = _walk(form_github, lambda c: c.type == "select" and c.props.get("name") == "enabled")
    assert len(enabled_selects_g) == 1
    assert enabled_selects_g[0].props.get("value") == "true"

    # brave is enabled=False
    spec_brave = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="brave",
    )
    form_brave = _edit_form_for_server(spec_brave, "brave")
    assert form_brave is not None
    enabled_selects_b = _walk(form_brave, lambda c: c.type == "select" and c.props.get("name") == "enabled")
    assert len(enabled_selects_b) == 1
    assert enabled_selects_b[0].props.get("value") == "false"


async def test_edit_form_name_field_read_only(test_db):
    """Edit form name field is read_only or disabled (name is the identifier)."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    form = _edit_form_for_server(spec, "github")
    assert form is not None
    name_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "name")
    assert len(name_fields) == 1
    props = name_fields[0].props
    assert props.get("read_only") is True or props.get("disabled") is True


async def test_delete_button_still_present_with_edit_form(test_db):
    """Delete button is still rendered alongside the inline edit form."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "mcp_servers"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    assert len(delete_btns) >= len(_SERVERS)


async def test_empty_args_env_in_edit_form(test_db):
    """Edit form for server with empty args/env shows empty strings."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="brave",
    )
    form = _edit_form_for_server(spec, "brave")
    assert form is not None
    args_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "args")
    assert len(args_fields) == 1
    assert args_fields[0].props.get("value") == ""
    env_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "env")
    assert len(env_fields) == 1
    assert env_fields[0].props.get("value") == ""
