"""Phase 10 Task A: Collapsible MCP server cards with filter.

Covers:
  - With servers and expand_server=None, all collapsed (no inline edit forms)
  - With expand_server="github", only github shows the edit form
  - Collapsed row has "편집" button with view_request action and expand_server param
  - Collapsed row shows command summary (truncated to 60 chars)
  - Collapsed row shows enabled badge
  - "삭제" button still present in collapsed rows
  - Filter form present at top of MCP servers card
  - With mcp_filter="git" only matching servers shown
  - Empty filter result shows correct message
  - "접기" button present in expanded card
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
        "env": {"TOKEN": "abc"},
        "enabled": True,
    },
    {
        "name": "local",
        "command": "python",
        "args": ["-m", "local_mcp"],
        "env": {},
        "enabled": False,
    },
    {
        "name": "foo",
        "command": "foo-server",
        "args": [],
        "env": {},
        "enabled": True,
    },
]


def _edit_forms_for_mcp(spec):
    """Return all settings_update_item forms for mcp_servers."""
    forms = _walk(spec.root, lambda c: c.type == "form")
    return [
        f for f in forms
        if (f.props.get("action") or {}).get("kind") == "settings_update_item"
        and (f.props.get("action") or {}).get("key") == "mcp_servers"
    ]


def _edit_form_for_server(spec, server_name):
    for f in _edit_forms_for_mcp(spec):
        action = f.props.get("action") or {}
        if action.get("match_value") == server_name:
            return f
    return None


def _view_request_buttons(spec):
    buttons = _walk(spec.root, lambda c: c.type == "button")
    return [
        b for b in buttons
        if (b.props.get("action") or {}).get("kind") == "view_request"
    ]


# ---------------------------------------------------------------------------
# Collapsed by default
# ---------------------------------------------------------------------------

async def test_all_collapsed_when_no_expand_server(test_db):
    """With expand_server=None, no inline edit forms are rendered."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    edit_forms = _edit_forms_for_mcp(spec)
    assert edit_forms == [], (
        f"Expected no edit forms when expand_server is None, got {len(edit_forms)}"
    )


async def test_only_expanded_server_has_edit_form(test_db):
    """With expand_server='github', only github shows the inline edit form."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    edit_forms = _edit_forms_for_mcp(spec)
    assert len(edit_forms) == 1, f"Expected 1 edit form, got {len(edit_forms)}"
    action = edit_forms[0].props.get("action") or {}
    assert action.get("match_value") == "github"


async def test_non_expanded_servers_still_collapsed(test_db):
    """With expand_server='github', local and foo have no edit form."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    assert _edit_form_for_server(spec, "local") is None
    assert _edit_form_for_server(spec, "foo") is None


# ---------------------------------------------------------------------------
# "편집" button in collapsed rows
# ---------------------------------------------------------------------------

async def test_edit_button_present_in_collapsed_row(test_db):
    """Collapsed row has a '편집' view_request button."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    vr_buttons = _view_request_buttons(spec)
    edit_btns = [b for b in vr_buttons if b.props.get("label") == "편집"]
    # One per server
    assert len(edit_btns) == len(_SERVERS), (
        f"Expected {len(_SERVERS)} '편집' buttons, got {len(edit_btns)}"
    )


async def test_edit_button_action_has_expand_server_param(test_db):
    """'편집' button dispatches view_request with expand_server param matching server name."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    vr_buttons = _view_request_buttons(spec)
    edit_btns = [b for b in vr_buttons if b.props.get("label") == "편집"]
    expand_values = set()
    for b in edit_btns:
        action = b.props.get("action") or {}
        params = action.get("params") or {}
        expand_values.add(params.get("expand_server"))
    expected = {srv["name"] for srv in _SERVERS}
    assert expand_values == expected, (
        f"Expected expand_server params {expected}, got {expand_values}"
    )


# ---------------------------------------------------------------------------
# Command summary in collapsed rows
# ---------------------------------------------------------------------------

async def test_collapsed_row_shows_command_summary(test_db):
    """Collapsed row shows a text component with the server's command."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    # Each server command should appear somewhere in a text value
    for srv in _SERVERS:
        cmd = srv["command"]
        assert any(cmd in v for v in text_values), (
            f"Command '{cmd}' not found in any text component"
        )


async def test_collapsed_row_command_truncated_at_60_chars(test_db):
    """Command summary is truncated to 60 chars."""
    long_command = "a" * 80
    servers = [{"name": "longcmd", "command": long_command, "args": [], "env": {}, "enabled": True}]
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": servers}),
    )
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    # No text value should contain the full 80-char command
    assert not any(long_command in v for v in text_values), (
        "Full 80-char command appeared — truncation not applied"
    )
    # But the first 60 chars should appear
    assert any(long_command[:60] in v for v in text_values), (
        "Truncated command prefix not found in any text component"
    )


# ---------------------------------------------------------------------------
# Enabled badge
# ---------------------------------------------------------------------------

async def test_collapsed_row_enabled_badge(test_db):
    """Collapsed row shows enabled/disabled badge text."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("활성" in v for v in text_values), "No '활성' badge found"
    assert any("비활성" in v for v in text_values), "No '비활성' badge found"


# ---------------------------------------------------------------------------
# Delete button in collapsed rows
# ---------------------------------------------------------------------------

async def test_delete_button_present_in_collapsed_rows(test_db):
    """Each collapsed row still has a delete button."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "mcp_servers"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    assert len(delete_btns) >= len(_SERVERS), (
        f"Expected at least {len(_SERVERS)} delete buttons, got {len(delete_btns)}"
    )


# ---------------------------------------------------------------------------
# Filter form
# ---------------------------------------------------------------------------

async def test_filter_form_present_in_mcp_card(test_db):
    """A filter form is present at the top of the MCP servers card."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    forms = _walk(spec.root, lambda c: c.type == "form")
    filter_forms = [
        f for f in forms
        if (f.props.get("action") or {}).get("kind") == "view_request"
        and any(
            ch.props.get("name") == "mcp_filter"
            for ch in _walk(f, lambda c: c.type == "field")
        )
    ]
    assert len(filter_forms) >= 1, "No filter form with 'mcp_filter' field found"


# ---------------------------------------------------------------------------
# Filter functionality
# ---------------------------------------------------------------------------

async def test_filter_shows_only_matching_servers(test_db):
    """With mcp_filter='git', only 'github' server's collapsed row is rendered."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        mcp_filter="git",
    )
    # github should have an edit button, local and foo should not
    vr_buttons = _view_request_buttons(spec)
    edit_btns = [b for b in vr_buttons if b.props.get("label") == "편집"]
    expand_values = {
        (b.props.get("action") or {}).get("params", {}).get("expand_server")
        for b in edit_btns
    }
    assert "github" in expand_values, "github should be visible with filter='git'"
    assert "local" not in expand_values, "local should be filtered out"
    assert "foo" not in expand_values, "foo should be filtered out"


async def test_filter_case_insensitive(test_db):
    """mcp_filter is case-insensitive."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        mcp_filter="GIT",
    )
    vr_buttons = _view_request_buttons(spec)
    edit_btns = [b for b in vr_buttons if b.props.get("label") == "편집"]
    expand_values = {
        (b.props.get("action") or {}).get("params", {}).get("expand_server")
        for b in edit_btns
    }
    assert "github" in expand_values, "github should match case-insensitive filter 'GIT'"


async def test_filter_empty_result_shows_no_match_message(test_db):
    """When filter matches nothing, shows '필터 조건에 일치하는 서버가 없습니다.'"""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        mcp_filter="zzz_no_match",
    )
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("필터 조건에 일치하는 서버가 없습니다" in v for v in text_values), (
        "No filter-empty message found"
    )


# ---------------------------------------------------------------------------
# Fold button in expanded card
# ---------------------------------------------------------------------------

async def test_fold_button_present_when_expanded(test_db):
    """Expanded card has a '접기' button that dispatches view_request."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
        expand_server="github",
    )
    vr_buttons = _view_request_buttons(spec)
    fold_btns = [b for b in vr_buttons if b.props.get("label") == "접기"]
    assert len(fold_btns) >= 1, "No '접기' button found in expanded card"


async def test_fold_button_not_present_when_collapsed(test_db):
    """No '접기' button when no server is expanded."""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore({"mcp_servers": _SERVERS}),
    )
    vr_buttons = _view_request_buttons(spec)
    fold_btns = [b for b in vr_buttons if b.props.get("label") == "접기"]
    assert len(fold_btns) == 0, f"Expected no '접기' buttons, got {len(fold_btns)}"


# ---------------------------------------------------------------------------
# Empty state (no servers, no filter)
# ---------------------------------------------------------------------------

async def test_no_servers_shows_default_empty_message(test_db):
    """When no servers and no filter, shows '등록된 MCP 서버가 없습니다.'"""
    spec = await settings_view.build(
        test_db,
        settings_store=FakeStore(),
    )
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("등록된 MCP 서버가 없습니다" in v for v in text_values)
