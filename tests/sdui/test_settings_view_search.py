# tests/sdui/test_settings_view_search.py
"""Tests for Phase 9: settings search + tab deep-linking."""
from breadmind.sdui.views import settings_view


def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_walk(ch, predicate))
    return out


def _find_text_values(component):
    """Collect all text component values in the tree."""
    texts = _walk(component, lambda c: c.type == "text")
    return [t.props.get("value", "") for t in texts]


class FakeStore:
    def __init__(self, data=None):
        self.data = data or {}

    async def get_setting(self, key):
        return self.data.get(key)


# ── Search card presence ──────────────────────────────────────────────────────

async def test_search_card_always_present(test_db):
    """The search card must appear even when no query is given."""
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    cards = _walk(spec.root, lambda c: c.id == "settings-search")
    assert len(cards) == 1


async def test_search_card_present_with_query(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="모델")
    cards = _walk(spec.root, lambda c: c.id == "settings-search")
    assert len(cards) == 1


async def test_search_card_has_form(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    forms = _walk(spec.root, lambda c: c.id == "settings-search-form")
    assert len(forms) == 1


async def test_search_form_has_q_field(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore())
    fields = _walk(spec.root, lambda c: c.id == "settings-search-q")
    assert len(fields) == 1
    assert fields[0].props["name"] == "q"
    assert fields[0].props["placeholder"] == "필드명 또는 키 검색"


# ── Results card ──────────────────────────────────────────────────────────────

async def test_no_results_card_when_q_is_none(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q=None)
    cards = _walk(spec.root, lambda c: c.id == "settings-results")
    assert len(cards) == 0


async def test_no_results_card_when_q_is_empty(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="")
    cards = _walk(spec.root, lambda c: c.id == "settings-results")
    assert len(cards) == 0


async def test_results_card_present_when_q_nonempty(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="모델")
    cards = _walk(spec.root, lambda c: c.id == "settings-results")
    assert len(cards) == 1


async def test_results_card_shows_query_text(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="프로바이더")
    texts = _find_text_values(spec.root)
    assert any("프로바이더" in t for t in texts)


async def test_no_match_shows_empty_message(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="zzznomatchzzz")
    texts = _find_text_values(spec.root)
    assert any("일치하는 설정이 없습니다" in t for t in texts)


async def test_matching_results_show_goto_buttons(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="모델")
    goto_buttons = _walk(spec.root, lambda c: c.id.startswith("settings-result-") and c.id.endswith("-goto"))
    assert len(goto_buttons) >= 1


async def test_goto_button_dispatches_view_request(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="모델")
    goto_buttons = _walk(spec.root, lambda c: c.id.startswith("settings-result-") and c.id.endswith("-goto"))
    assert len(goto_buttons) >= 1
    action = goto_buttons[0].props["action"]
    assert action["kind"] == "view_request"
    assert action["view_key"] == "settings_view"
    assert "active_tab" in action["params"]


async def test_results_appear_before_tabs(test_db):
    """Results card should appear before the tabs component in page_children."""
    spec = await settings_view.build(test_db, settings_store=FakeStore(), q="모델")
    # build() returns an unwrapped page whose root is the settings page directly.
    root = spec.root
    child_ids = [ch.id for ch in root.children]
    assert "settings-results" in child_ids
    assert "settings-tabs" in child_ids
    assert child_ids.index("settings-results") < child_ids.index("settings-tabs")


# ── Tab deep-linking ──────────────────────────────────────────────────────────

async def test_active_tab_none_no_default_active(test_db):
    """When active_tab is None the tabs component should have no default_active prop."""
    spec = await settings_view.build(test_db, settings_store=FakeStore(), active_tab=None)
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    assert "default_active" not in tabs_comps[0].props


async def test_active_tab_invalid_no_default_active(test_db):
    """When active_tab is not a known tab ID, default_active should be absent."""
    spec = await settings_view.build(test_db, settings_store=FakeStore(), active_tab="nonexistent_tab")
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    assert "default_active" not in tabs_comps[0].props


async def test_active_tab_quick_start_is_index_0(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), active_tab="quick_start")
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    assert tabs_comps[0].props.get("default_active") == 0


async def test_active_tab_agent_behavior_is_index_1(test_db):
    spec = await settings_view.build(test_db, settings_store=FakeStore(), active_tab="agent_behavior")
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert tabs_comps[0].props.get("default_active") == 1


async def test_active_tab_monitoring_non_admin(test_db):
    """For non-admin: monitoring is at index 3 (no safety tab)."""
    spec = await settings_view.build(test_db, settings_store=FakeStore(), active_tab="monitoring")
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    # Non-admin: quick_start=0, agent_behavior=1, integrations=2, monitoring=3
    assert tabs_comps[0].props.get("default_active") == 3


async def test_active_tab_monitoring_admin(test_db):
    """For admin: monitoring is at index 4 (safety tab inserted before it)."""
    store = FakeStore({"safety_permissions": {"admin_users": ["admin"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="admin", active_tab="monitoring")
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(tabs_comps) == 1
    # Admin: quick_start=0, agent_behavior=1, integrations=2, safety=3, monitoring=4
    assert tabs_comps[0].props.get("default_active") == 4


async def test_active_tab_memory_non_admin(test_db):
    """For non-admin: memory is at index 4."""
    spec = await settings_view.build(test_db, settings_store=FakeStore(), active_tab="memory")
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    # Non-admin: quick_start=0, agent_behavior=1, integrations=2, monitoring=3, memory=4
    assert tabs_comps[0].props.get("default_active") == 4


async def test_search_and_active_tab_together(test_db):
    """Search query and active_tab can coexist."""
    spec = await settings_view.build(
        test_db, settings_store=FakeStore(), q="모델", active_tab="agent_behavior"
    )
    results_cards = _walk(spec.root, lambda c: c.id == "settings-results")
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    assert len(results_cards) == 1
    assert tabs_comps[0].props.get("default_active") == 1
