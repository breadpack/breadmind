# tests/sdui/test_settings_view_phase5_vault.py
"""Phase 5 Task 2: vault card full-management UI tests.

Covers listing entries with timestamps, delete buttons, add/rotate form,
empty state, unavailable state.
"""
from breadmind.sdui.views import settings_view


def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_walk(ch, predicate))
    return out


# ---------------------------------------------------------------------------
# Fake stores / db helpers
# ---------------------------------------------------------------------------

_ADMIN_EXTRA = {"safety_permissions": {"admin_users": ["admin"]}}


class _FakeStoreAdmin:
    """Minimal settings store that supports admin user and list_settings_by_prefix."""

    def __init__(self, vault_keys=None, vault_data=None, extra=None):
        # vault_keys: list of full "vault:xxx" key strings returned by list_settings_by_prefix
        # vault_data: dict mapping full key -> setting dict
        self._vault_keys = vault_keys or []
        self._vault_data = vault_data or {}
        self._extra = {**_ADMIN_EXTRA, **(extra or {})}

    async def get_setting(self, key):
        if key in self._extra:
            return self._extra[key]
        return self._vault_data.get(key)

    async def list_settings_by_prefix(self, prefix):
        return [k for k in self._vault_keys if k.startswith(prefix)]


class _FakeStoreNoList:
    """Store without list_settings_by_prefix — simulates unavailable vault."""

    def __init__(self):
        self.data = {**_ADMIN_EXTRA}

    async def get_setting(self, key):
        return self.data.get(key)


# ---------------------------------------------------------------------------
# _safe_list_vault_entries unit tests
# ---------------------------------------------------------------------------

async def test_safe_list_vault_entries_returns_none_when_no_list_method(test_db):
    """_safe_list_vault_entries returns None when db has no list_settings_by_prefix (unavailable)."""

    class NoListDB:
        async def get_setting(self, key):
            return None

    result = await settings_view._safe_list_vault_entries(NoListDB())
    assert result is None


async def test_safe_list_vault_entries_returns_empty_for_no_keys(test_db):
    """_safe_list_vault_entries returns [] when no vault keys exist."""

    class EmptyDB:
        async def list_settings_by_prefix(self, prefix):
            return []

        async def get_setting(self, key):
            return None

    result = await settings_view._safe_list_vault_entries(EmptyDB())
    assert result == []


async def test_safe_list_vault_entries_extracts_id_and_stored_at(test_db):
    """_safe_list_vault_entries extracts credential id and stored_at from each entry."""

    class PopulatedDB:
        async def list_settings_by_prefix(self, prefix):
            return ["vault:ssh:host1", "vault:messenger:slack"]

        async def get_setting(self, key):
            data = {
                "vault:ssh:host1": {"encrypted": "xxx", "stored_at": 1744375380.0},
                "vault:messenger:slack": {"encrypted": "yyy", "stored_at": 1744375400.0, "metadata": {"note": "test"}},
            }
            return data.get(key)

    result = await settings_view._safe_list_vault_entries(PopulatedDB())
    assert len(result) == 2
    ids = [e["id"] for e in result]
    assert "ssh:host1" in ids
    assert "messenger:slack" in ids


async def test_safe_list_vault_entries_has_metadata_flag(test_db):
    """_safe_list_vault_entries includes full metadata dict (None when absent)."""

    class DB:
        async def list_settings_by_prefix(self, prefix):
            return ["vault:no_meta", "vault:with_meta"]

        async def get_setting(self, key):
            data = {
                "vault:no_meta": {"encrypted": "a", "stored_at": 1000.0},
                "vault:with_meta": {"encrypted": "b", "stored_at": 2000.0, "metadata": {"k": "v"}},
            }
            return data.get(key)

    result = await settings_view._safe_list_vault_entries(DB())
    by_id = {e["id"]: e for e in result}
    assert by_id["no_meta"]["metadata"] is None
    assert by_id["with_meta"]["metadata"] == {"k": "v"}


async def test_safe_list_vault_entries_returns_none_on_exception(test_db):
    """_safe_list_vault_entries returns None when list_settings_by_prefix raises (unavailable)."""

    class BrokenDB:
        async def list_settings_by_prefix(self, prefix):
            raise RuntimeError("DB connection failed")

    result = await settings_view._safe_list_vault_entries(BrokenDB())
    assert result is None


async def test_safe_list_vault_entries_limits_to_100(test_db):
    """_safe_list_vault_entries limits output to at most 100 entries."""

    class BigDB:
        async def list_settings_by_prefix(self, prefix):
            return [f"vault:key{i}" for i in range(150)]

        async def get_setting(self, key):
            return {"encrypted": "x", "stored_at": 1000.0}

    result = await settings_view._safe_list_vault_entries(BigDB())
    assert len(result) <= 100


# ---------------------------------------------------------------------------
# _format_timestamp unit tests
# ---------------------------------------------------------------------------

def test_format_timestamp_returns_formatted_string():
    """_format_timestamp converts Unix timestamp to YYYY-MM-DD HH:MM string."""
    # Use a fixed timestamp: 2026-04-11 00:00:00 UTC would be locale-dependent,
    # so just verify format rather than exact value.
    ts = 1744327200.0  # some fixed point in time
    result = settings_view._format_timestamp(ts)
    # Should be 16 chars like "2026-04-11 14:23"
    assert len(result) == 16
    assert result[4] == "-"
    assert result[7] == "-"
    assert result[10] == " "
    assert result[13] == ":"


def test_format_timestamp_none_returns_dash():
    """_format_timestamp returns '-' when ts is None."""
    result = settings_view._format_timestamp(None)
    assert result == "-"


def test_format_timestamp_zero_returns_string():
    """_format_timestamp handles ts=0 without crashing."""
    result = settings_view._format_timestamp(0)
    assert isinstance(result, str)
    assert len(result) == 16


# ---------------------------------------------------------------------------
# Vault card full-build tests
# ---------------------------------------------------------------------------

async def test_vault_card_lists_entries(test_db):
    """Vault card renders an entry row for each credential when db returns keys (admin)."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:host1", "vault:messenger:slack"],
        vault_data={
            "vault:ssh:host1": {"encrypted": "xxx", "stored_at": 1744375380.0},
            "vault:messenger:slack": {"encrypted": "yyy", "stored_at": 1744375400.0},
        },
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    # Both credential IDs should appear somewhere in text components
    assert any("ssh:host1" in v for v in text_values)
    assert any("messenger:slack" in v for v in text_values)


async def test_vault_card_each_entry_has_delete_button(test_db):
    """Each vault entry has a delete button with credential_delete action and correct id (admin)."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:host1", "vault:api:openai"],
        vault_data={
            "vault:ssh:host1": {"encrypted": "a", "stored_at": 1744375380.0},
            "vault:api:openai": {"encrypted": "b", "stored_at": 1744375380.0},
        },
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_actions = [
        b.props.get("action", {})
        for b in buttons
        if b.props.get("action", {}).get("kind") == "credential_delete"
    ]
    cred_ids_in_actions = {a.get("credential_id") for a in delete_actions}
    assert "ssh:host1" in cred_ids_in_actions
    assert "api:openai" in cred_ids_in_actions


async def test_vault_card_has_add_form(test_db):
    """Vault card contains a form that dispatches credential_store (admin)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    forms = _walk(spec.root, lambda c: c.type == "form")
    store_forms = [
        f for f in forms
        if (f.props.get("action") or {}).get("kind") == "credential_store"
    ]
    assert len(store_forms) == 1


async def test_vault_card_add_form_has_password_field(test_db):
    """Vault card add form has a 'value' field of type 'password' (admin)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    forms = _walk(spec.root, lambda c: c.type == "form")
    store_form = next(
        f for f in forms
        if (f.props.get("action") or {}).get("kind") == "credential_store"
    )
    fields = _walk(store_form, lambda c: c.type == "field")
    by_name = {f.props.get("name"): f.props for f in fields}
    assert "value" in by_name
    assert by_name["value"].get("type") == "password"


async def test_vault_card_add_form_has_credential_id_field(test_db):
    """Vault card add form has a 'credential_id' text field (admin)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    forms = _walk(spec.root, lambda c: c.type == "form")
    store_form = next(
        f for f in forms
        if (f.props.get("action") or {}).get("kind") == "credential_store"
    )
    fields = _walk(store_form, lambda c: c.type == "field")
    by_name = {f.props.get("name"): f.props for f in fields}
    assert "credential_id" in by_name
    assert by_name["credential_id"].get("type") == "text"


async def test_vault_card_empty_state_message(test_db):
    """Vault card shows '저장된 자격증명이 없습니다.' when no entries exist (admin)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("저장된 자격증명이 없습니다" in v for v in text_values)


async def test_vault_card_unavailable_state_when_no_list_method(test_db):
    """Vault card shows unavailable text when db lacks list_settings_by_prefix (admin)."""
    store = _FakeStoreNoList()
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("자격증명 금고를 불러올 수 없습니다" in v for v in text_values)


async def test_vault_card_timestamps_formatted(test_db):
    """Vault entries show stored_at formatted as 'YYYY-MM-DD HH:MM' (admin)."""
    # 1744375380.0 is in 2025; exact local time depends on TZ but format is fixed.
    store = _FakeStoreAdmin(
        vault_keys=["vault:test:key"],
        vault_data={"vault:test:key": {"encrypted": "x", "stored_at": 1744375380.0}},
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    # At least one text should contain a date-like string "20xx-"
    date_texts = [v for v in text_values if "20" in v and "-" in v and ":" in v]
    assert len(date_texts) >= 1


async def test_vault_card_still_has_heading(test_db):
    """Vault card always renders the '자격증명 금고' heading (admin)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    headings = _walk(spec.root, lambda c: c.type == "heading")
    vault_headings = [h for h in headings if h.props.get("value") == "자격증명 금고"]
    assert len(vault_headings) >= 1


async def test_vault_card_renders_without_crash_on_get_setting_error(test_db):
    """Vault card renders cleanly when individual get_setting calls fail (admin)."""

    class ErrorOnGetDB:
        async def list_settings_by_prefix(self, prefix):
            return ["vault:broken"]

        async def get_setting(self, key):
            raise RuntimeError("broken")

    # Build an admin store with list_settings_by_prefix
    class AdminStoreWithBrokenDB:
        async def get_setting(self, key):
            data = {**_ADMIN_EXTRA}
            return data.get(key)

        async def list_settings_by_prefix(self, prefix):
            # Return a key but the data fetch will fail (simulated by error_db)
            return ["vault:broken"]

    admin_store = AdminStoreWithBrokenDB()
    # Use a db that raises on get_setting
    error_db = ErrorOnGetDB()
    spec = await settings_view.build(error_db, settings_store=admin_store, user_id="admin")
    # Should not crash; vault card renders with empty or unavailable state
    assert spec.root.type == "page"
    headings = _walk(spec.root, lambda c: c.type == "heading")
    vault_headings = [h for h in headings if h.props.get("value") == "자격증명 금고"]
    assert len(vault_headings) >= 1


async def test_vault_card_no_description_readonly_text(test_db):
    """The old '(읽기 전용)' description text is no longer present (admin)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert not any("읽기 전용" in v for v in text_values)
