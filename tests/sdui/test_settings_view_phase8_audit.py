"""Phase 8 SDUI settings view tests — audit log card.

Covers:
  - Audit log card is present in the advanced tab
  - Empty state renders when no entries
  - Entries render with newest first
  - Display is capped at ~30 entries even when 100 exist
  - Non-admin users do not see the card (advanced tab is admin-gated)
"""
from breadmind.sdui.views import settings_view


def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_walk(ch, predicate))
    return out


def _find_by_id(spec, component_id):
    results = _walk(spec.root, lambda c: c.id == component_id)
    return results[0] if results else None


def _all_text_values(spec):
    texts = _walk(spec.root, lambda c: c.type == "text")
    return [t.props.get("value", "") for t in texts]


class FakeStore:
    def __init__(self, data=None):
        self.data = data or {}

    async def get_setting(self, key):
        return self.data.get(key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entries(n: int, base_ts: float = 1000.0) -> list[dict]:
    return [
        {
            "ts": base_ts + float(i),
            "action": "settings_write",
            "key": "llm",
            "user": f"user{i}",
            "summary": f"entry {i}",
        }
        for i in range(n)
    ]


async def _build_admin(store_data: dict | None = None):
    data = {"safety_permissions": {"admin_users": ["alice"]}}
    if store_data:
        data.update(store_data)
    store = FakeStore(data)
    return await settings_view.build(None, settings_store=store, user_id="alice")


async def _build_nonadmin(store_data: dict | None = None):
    data = {"safety_permissions": {"admin_users": ["alice"]}}
    if store_data:
        data.update(store_data)
    store = FakeStore(data)
    return await settings_view.build(None, settings_store=store, user_id="bob")


# ---------------------------------------------------------------------------
# Audit card presence
# ---------------------------------------------------------------------------

async def test_audit_card_present_in_advanced_tab():
    spec = await _build_admin()
    card = _find_by_id(spec, "adv-audit")
    assert card is not None, "adv-audit card not found in advanced tab"


async def test_audit_card_has_heading():
    spec = await _build_admin()
    heading = _find_by_id(spec, "adv-audit-h")
    assert heading is not None
    assert heading.props.get("value") == "변경 이력"


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

async def test_audit_card_empty_state_no_entries():
    spec = await _build_admin()
    empty = _find_by_id(spec, "adv-audit-empty")
    assert empty is not None
    assert "기록이 없습니다" in empty.props.get("value", "")


async def test_audit_card_no_empty_state_when_entries_exist():
    entries = _make_entries(3)
    spec = await _build_admin({"sdui_audit_log": entries})
    empty = _find_by_id(spec, "adv-audit-empty")
    assert empty is None


# ---------------------------------------------------------------------------
# Renders entries
# ---------------------------------------------------------------------------

async def test_audit_card_renders_three_entries():
    entries = _make_entries(3, base_ts=1000.0)
    spec = await _build_admin({"sdui_audit_log": entries})
    # There should be 3 kv rows inside adv-audit
    card = _find_by_id(spec, "adv-audit")
    rows = _walk(card, lambda c: c.id.startswith("adv-audit-row-"))
    assert len(rows) == 3


async def test_audit_card_entries_newest_first():
    entries = _make_entries(3, base_ts=1000.0)
    # entry 0: ts=1000, entry 1: ts=1001, entry 2: ts=1002
    spec = await _build_admin({"sdui_audit_log": entries})
    card = _find_by_id(spec, "adv-audit")
    rows = _walk(card, lambda c: c.id.startswith("adv-audit-row-"))
    # First row displayed should be the newest (entry 2)
    first_row_items = rows[0].props.get("items", [])
    user_item = next((it for it in first_row_items if it["key"] == "사용자"), None)
    assert user_item is not None
    # The newest entry is user2
    assert user_item["value"] == "user2"


async def test_audit_card_shows_user_action_key_summary():
    entries = [
        {
            "ts": 1234567890.0,
            "action": "settings_write",
            "key": "llm",
            "user": "testuser",
            "summary": "1 field(s) updated: default_provider",
        }
    ]
    spec = await _build_admin({"sdui_audit_log": entries})
    card = _find_by_id(spec, "adv-audit")
    rows = _walk(card, lambda c: c.id.startswith("adv-audit-row-"))
    assert len(rows) == 1
    items = rows[0].props.get("items", [])
    keys_in_row = {it["key"]: it["value"] for it in items}
    assert keys_in_row.get("사용자") == "testuser"
    assert keys_in_row.get("작업") == "settings_write"
    assert keys_in_row.get("키") == "llm"
    assert "default_provider" in keys_in_row.get("요약", "")


# ---------------------------------------------------------------------------
# Cap at 30
# ---------------------------------------------------------------------------

async def test_audit_card_caps_display_at_30_when_100_entries():
    entries = _make_entries(100)
    spec = await _build_admin({"sdui_audit_log": entries})
    card = _find_by_id(spec, "adv-audit")
    rows = _walk(card, lambda c: c.id.startswith("adv-audit-row-"))
    assert len(rows) == 30


async def test_audit_card_newest_30_of_100():
    entries = _make_entries(100, base_ts=1000.0)
    # entries 70..99 should be displayed (newest 30)
    spec = await _build_admin({"sdui_audit_log": entries})
    card = _find_by_id(spec, "adv-audit")
    rows = _walk(card, lambda c: c.id.startswith("adv-audit-row-"))
    # First row displayed = newest = entry 99
    first_items = {it["key"]: it["value"] for it in rows[0].props.get("items", [])}
    assert first_items.get("사용자") == "user99"
    # Last row displayed = entry 70
    last_items = {it["key"]: it["value"] for it in rows[-1].props.get("items", [])}
    assert last_items.get("사용자") == "user70"


# ---------------------------------------------------------------------------
# Non-admin does not see audit card
# ---------------------------------------------------------------------------

async def test_non_admin_does_not_see_audit_card():
    spec = await _build_nonadmin()
    card = _find_by_id(spec, "adv-audit")
    assert card is None, "Non-admin should not see audit card (advanced tab is admin-only)"


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------

async def test_audit_card_timestamp_formatted():
    import datetime
    ts = datetime.datetime(2024, 3, 15, 9, 30).timestamp()
    entries = [
        {"ts": ts, "action": "settings_write", "key": "llm", "user": "alice", "summary": "1 field(s) updated: x"}
    ]
    spec = await _build_admin({"sdui_audit_log": entries})
    card = _find_by_id(spec, "adv-audit")
    rows = _walk(card, lambda c: c.id.startswith("adv-audit-row-"))
    items = {it["key"]: it["value"] for it in rows[0].props.get("items", [])}
    ts_value = items.get("시각", "")
    assert "2024-03-15" in ts_value
    assert "09:30" in ts_value
