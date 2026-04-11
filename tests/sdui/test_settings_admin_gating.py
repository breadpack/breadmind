# tests/sdui/test_settings_admin_gating.py
"""Admin gating tests for the SDUI settings view and action handler (Phase 4 Task 3).

View-level:
  - Non-admin user does NOT see 안전 & 권한 or 고급 tabs.
  - Admin user DOES see both tabs.
  - Empty admin_users → nobody is admin → tabs hidden.
  - Hint text visible for non-admin users.

Action-level:
  - Bootstrap: with no admin_users set, any user can append safety_permissions_admin_users.
  - After bootstrap (admin_users = ["alice"]): non-admin "bob" cannot write safety_blacklist.
  - Admin "alice" CAN write safety_blacklist.
  - Non-admin write to a non-admin key (e.g. "llm") still succeeds.
"""
import pytest

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.actions import ActionHandler
from breadmind.sdui.views import settings_view


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_walk(ch, predicate))
    return out


def _tab_labels(spec):
    tabs_comps = _walk(spec.root, lambda c: c.type == "tabs")
    if not tabs_comps:
        return []
    return [ch.props.get("label", "") for ch in tabs_comps[0].children]


class FakeStore:
    def __init__(self, data=None):
        self.data: dict = dict(data or {})

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value


# ---------------------------------------------------------------------------
# View-level gating
# ---------------------------------------------------------------------------

async def test_non_admin_tabs_hidden(test_db):
    """Non-admin user does NOT see 안전 & 권한 or 고급 tabs."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="bob")
    labels = _tab_labels(spec)
    assert "안전 & 권한" not in labels
    assert "고급" not in labels


async def test_admin_tabs_visible(test_db):
    """Admin user sees 안전 & 권한 and 고급 tabs."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="alice")
    labels = _tab_labels(spec)
    assert "안전 & 권한" in labels
    assert "고급" in labels


async def test_admin_seven_tabs_correct_order(test_db):
    """Admin user sees all 7 tabs in the correct order."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="alice")
    labels = _tab_labels(spec)
    assert labels == [
        "빠른 시작",
        "에이전트 동작",
        "통합",
        "안전 & 권한",
        "모니터링",
        "메모리",
        "고급",
    ]


async def test_non_admin_five_tabs_correct_order(test_db):
    """Non-admin user sees 5 tabs (safety & advanced excluded)."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="bob")
    labels = _tab_labels(spec)
    assert labels == [
        "빠른 시작",
        "에이전트 동작",
        "통합",
        "모니터링",
        "메모리",
    ]


async def test_empty_admin_users_nobody_is_admin(test_db):
    """When admin_users is an empty list, nobody is admin and tabs are hidden."""
    store = FakeStore({"safety_permissions": {"admin_users": []}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="alice")
    labels = _tab_labels(spec)
    assert "안전 & 권한" not in labels
    assert "고급" not in labels


async def test_missing_admin_users_key_nobody_is_admin(test_db):
    """When safety_permissions has no admin_users key, nobody is admin."""
    store = FakeStore({"safety_permissions": {}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="alice")
    labels = _tab_labels(spec)
    assert "안전 & 권한" not in labels
    assert "고급" not in labels


async def test_no_user_id_is_non_admin(test_db):
    """When user_id is None, the user is non-admin and tabs are hidden."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id=None)
    labels = _tab_labels(spec)
    assert "안전 & 권한" not in labels
    assert "고급" not in labels


async def test_no_store_is_non_admin(test_db):
    """Without a settings_store the user is non-admin and tabs are hidden."""
    spec = await settings_view.build(test_db, user_id="alice")
    labels = _tab_labels(spec)
    assert "안전 & 권한" not in labels
    assert "고급" not in labels


async def test_hint_text_shown_for_non_admin(test_db):
    """A hint text component is shown for non-admin users."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="bob")
    texts = _walk(spec.root, lambda c: c.type == "text" and c.id == "settings-admin-hint")
    assert len(texts) == 1
    assert "관리자" in texts[0].props.get("value", "")


async def test_hint_text_not_shown_for_admin(test_db):
    """The admin hint text should NOT be shown for an admin user."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    spec = await settings_view.build(test_db, settings_store=store, user_id="alice")
    texts = _walk(spec.root, lambda c: c.type == "text" and c.id == "settings-admin-hint")
    assert len(texts) == 0


# ---------------------------------------------------------------------------
# Action-level gating: fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def bus(test_db):
    store = FlowEventStore(test_db)
    event_bus = FlowEventBus(store=store, redis=None)
    await event_bus.start()
    try:
        yield event_bus
    finally:
        await event_bus.stop()


# ---------------------------------------------------------------------------
# Bootstrap: empty admin_users → any user can append safety_permissions_admin_users
# ---------------------------------------------------------------------------

async def test_bootstrap_append_admin_user_succeeds_when_no_admins(bus):
    """Bootstrap: with no admin_users set, any user can append safety_permissions_admin_users."""
    store = FakeStore()  # no safety_permissions at all
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_permissions_admin_users", "values": {"user": "alice"}},
        user_id="alice",
    )
    assert result["ok"] is True, f"Expected bootstrap to succeed, got: {result}"


async def test_bootstrap_empty_admin_list_allows_append(bus):
    """Bootstrap: even with an explicit empty admin_users list, append is allowed."""
    store = FakeStore({"safety_permissions": {"admin_users": []}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_permissions_admin_users", "values": {"user": "bob"}},
        user_id="bob",
    )
    assert result["ok"] is True, f"Expected bootstrap append to succeed, got: {result}"


# ---------------------------------------------------------------------------
# Post-bootstrap: admin_users = ["alice"]
# ---------------------------------------------------------------------------

async def test_non_admin_cannot_write_safety_blacklist(bus):
    """After bootstrap, non-admin bob cannot write safety_blacklist."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "safety_blacklist", "values": {"shell": ["rm_rf"]}},
        user_id="bob",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()


async def test_admin_can_write_safety_blacklist(bus):
    """Admin alice CAN write safety_blacklist."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "safety_blacklist", "values": {"shell": ["rm_rf"]}},
        user_id="alice",
    )
    assert result["ok"] is True, f"Expected admin write to succeed, got: {result}"


async def test_non_admin_cannot_append_safety_blacklist(bus):
    """Non-admin bob cannot append to safety_blacklist."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_blacklist", "values": {"domain": "shell", "tool": "rm_rf"}},
        user_id="bob",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()


async def test_admin_can_append_safety_blacklist(bus):
    """Admin alice CAN append to safety_blacklist."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_blacklist", "values": {"domain": "shell", "tool": "rm_rf"}},
        user_id="alice",
    )
    assert result["ok"] is True, f"Expected admin append to succeed, got: {result}"


async def test_non_admin_cannot_write_tool_security(bus):
    """Non-admin cannot write tool_security."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "tool_security", "values": {"base_directory": "/tmp"}},
        user_id="bob",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()


async def test_non_admin_cannot_write_system_timeouts(bus):
    """Non-admin cannot write system_timeouts."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "system_timeouts", "values": {"tool_call": 120}},
        user_id="bob",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()


async def test_non_admin_can_write_llm_settings(bus):
    """Non-admin can still write non-admin-gated keys like 'llm'."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "llm",
            "values": {"default_provider": "gemini", "default_model": "gemini-2.5-pro", "tool_call_max_turns": 10},
        },
        user_id="bob",
    )
    assert result["ok"] is True, f"Expected non-admin llm write to succeed, got: {result}"


async def test_post_bootstrap_second_append_requires_admin(bus):
    """After bootstrap adds first admin, a second non-admin user is blocked."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_permissions_admin_users", "values": {"user": "charlie"}},
        user_id="bob",  # not an admin
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()


async def test_admin_can_append_more_admins(bus):
    """An existing admin can append more users to admin_users."""
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_permissions_admin_users", "values": {"user": "charlie"}},
        user_id="alice",
    )
    assert result["ok"] is True, f"Expected admin to add another admin, got: {result}"
