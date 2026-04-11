# tests/sdui/test_settings_view_phase10_vault.py
"""Phase 10 Task B: vault card grouping, metadata display, rotation hint tests."""
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
    def __init__(self, vault_keys=None, vault_data=None, extra=None):
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
    def __init__(self):
        self.data = {**_ADMIN_EXTRA}

    async def get_setting(self, key):
        return self.data.get(key)


# ---------------------------------------------------------------------------
# Part 1: _safe_list_vault_entries extracts group and full metadata
# ---------------------------------------------------------------------------

async def test_safe_list_vault_entries_includes_group(test_db):
    """Each entry dict now includes a 'group' field derived from the id prefix."""

    class DB:
        async def list_settings_by_prefix(self, prefix):
            return ["vault:ssh:host1", "vault:oauth:google"]

        async def get_setting(self, key):
            return {"encrypted": "x", "stored_at": 1000.0}

    result = await settings_view._safe_list_vault_entries(DB())
    assert result is not None
    by_id = {e["id"]: e for e in result}
    assert by_id["ssh:host1"]["group"] == "ssh"
    assert by_id["oauth:google"]["group"] == "oauth"


async def test_safe_list_vault_entries_group_is_gita_when_no_colon(test_db):
    """Entries without ':' in the id are grouped under '기타'."""

    class DB:
        async def list_settings_by_prefix(self, prefix):
            return ["vault:mykey"]

        async def get_setting(self, key):
            return {"encrypted": "x", "stored_at": 1000.0}

    result = await settings_view._safe_list_vault_entries(DB())
    assert result is not None
    assert result[0]["group"] == "기타"


async def test_safe_list_vault_entries_includes_full_metadata(test_db):
    """Each entry dict now includes the full 'metadata' dict, not just has_metadata bool."""

    class DB:
        async def list_settings_by_prefix(self, prefix):
            return ["vault:ssh:host1", "vault:ssh:host2"]

        async def get_setting(self, key):
            data = {
                "vault:ssh:host1": {
                    "encrypted": "x",
                    "stored_at": 1000.0,
                    "metadata": {"description": "Prod SSH", "created_by": "alice"},
                },
                "vault:ssh:host2": {"encrypted": "y", "stored_at": 2000.0},
            }
            return data.get(key)

    result = await settings_view._safe_list_vault_entries(DB())
    assert result is not None
    by_id = {e["id"]: e for e in result}
    assert by_id["ssh:host1"]["metadata"] == {"description": "Prod SSH", "created_by": "alice"}
    assert by_id["ssh:host2"]["metadata"] is None


async def test_safe_list_vault_entries_empty_metadata_is_none(test_db):
    """Empty metadata dict results in metadata=None (treated as no metadata)."""

    class DB:
        async def list_settings_by_prefix(self, prefix):
            return ["vault:ssh:host1"]

        async def get_setting(self, key):
            return {"encrypted": "x", "stored_at": 1000.0, "metadata": {}}

    result = await settings_view._safe_list_vault_entries(DB())
    assert result is not None
    assert result[0]["metadata"] is None


# ---------------------------------------------------------------------------
# Part 2: _vault_card groups entries by prefix
# ---------------------------------------------------------------------------

async def test_vault_card_groups_by_prefix(test_db):
    """Vault card renders a sub-heading for each group (ssh, oauth)."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:host1", "vault:ssh:host2", "vault:ssh:host3",
                    "vault:oauth:google", "vault:oauth:github"],
        vault_data={
            "vault:ssh:host1": {"encrypted": "a", "stored_at": 1000.0},
            "vault:ssh:host2": {"encrypted": "b", "stored_at": 1001.0},
            "vault:ssh:host3": {"encrypted": "c", "stored_at": 1002.0},
            "vault:oauth:google": {"encrypted": "d", "stored_at": 1003.0},
            "vault:oauth:github": {"encrypted": "e", "stored_at": 1004.0},
        },
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    headings = _walk(spec.root, lambda c: c.type == "heading")
    heading_values = [h.props.get("value", "") for h in headings]
    # Both groups should appear as headings
    assert any("ssh" in v for v in heading_values)
    assert any("oauth" in v for v in heading_values)


async def test_vault_card_group_heading_shows_count(test_db):
    """Group headings include the count of entries, e.g., 'ssh (3개)'."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:host1", "vault:ssh:host2", "vault:ssh:host3"],
        vault_data={
            "vault:ssh:host1": {"encrypted": "a", "stored_at": 1000.0},
            "vault:ssh:host2": {"encrypted": "b", "stored_at": 1001.0},
            "vault:ssh:host3": {"encrypted": "c", "stored_at": 1002.0},
        },
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    headings = _walk(spec.root, lambda c: c.type == "heading")
    heading_values = [h.props.get("value", "") for h in headings]
    assert any("ssh" in v and "3" in v for v in heading_values)


async def test_vault_card_group_heading_single_entry_count(test_db):
    """Group heading shows '(1개)' when only one entry in the group."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:only"],
        vault_data={"vault:ssh:only": {"encrypted": "a", "stored_at": 1000.0}},
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    headings = _walk(spec.root, lambda c: c.type == "heading")
    heading_values = [h.props.get("value", "") for h in headings]
    assert any("ssh" in v and "1" in v for v in heading_values)


async def test_vault_card_gita_group_for_no_colon(test_db):
    """Entries without ':' in the id appear in the '기타' group."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:mykey"],
        vault_data={"vault:mykey": {"encrypted": "a", "stored_at": 1000.0}},
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    headings = _walk(spec.root, lambda c: c.type == "heading")
    heading_values = [h.props.get("value", "") for h in headings]
    assert any("기타" in v for v in heading_values)


# ---------------------------------------------------------------------------
# Part 2: metadata kv display in entry rows
# ---------------------------------------------------------------------------

async def test_vault_entry_row_shows_metadata_kv(test_db):
    """Vault entry with non-empty metadata renders a kv component."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:prod"],
        vault_data={
            "vault:ssh:prod": {
                "encrypted": "x",
                "stored_at": 1000.0,
                "metadata": {"description": "Prod SSH", "created_by": "alice"},
            }
        },
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    # Expect kv component with description key
    kvs = _walk(spec.root, lambda c: c.type == "kv")
    # Find kv that contains description item
    found = False
    for kv in kvs:
        items = kv.props.get("items", [])
        for item in items:
            if item.get("key") == "description":
                found = True
                break
    assert found, "Expected kv with 'description' key for metadata entry"


async def test_vault_entry_row_no_kv_when_no_metadata(test_db):
    """Vault entry with no metadata does not show metadata kv (only audit kv rows allowed)."""
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:plain"],
        vault_data={"vault:ssh:plain": {"encrypted": "x", "stored_at": 1000.0}},
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    # kv components that have items with keys matching metadata-like patterns
    kvs = _walk(spec.root, lambda c: c.type == "kv")
    # Audit log kv may contain "시각", "사용자", etc. — check no kv has "description" or "created_by"
    for kv in kvs:
        items = kv.props.get("items", [])
        keys = [item.get("key") for item in items]
        assert "description" not in keys
        assert "created_by" not in keys


async def test_vault_entry_metadata_value_truncated(test_db):
    """Metadata values longer than 80 chars are truncated in the kv display."""
    long_value = "x" * 100
    store = _FakeStoreAdmin(
        vault_keys=["vault:ssh:prod"],
        vault_data={
            "vault:ssh:prod": {
                "encrypted": "x",
                "stored_at": 1000.0,
                "metadata": {"description": long_value},
            }
        },
    )
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    kvs = _walk(spec.root, lambda c: c.type == "kv")
    for kv in kvs:
        items = kv.props.get("items", [])
        for item in items:
            if item.get("key") == "description":
                assert len(item.get("value", "")) <= 83  # 80 chars + "..."


# ---------------------------------------------------------------------------
# Part 3: form description field and rotation hint
# ---------------------------------------------------------------------------

async def test_vault_form_has_description_field(test_db):
    """Vault add form has an optional 'description' text field."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    forms = _walk(spec.root, lambda c: c.type == "form")
    store_form = next(
        f for f in forms
        if (f.props.get("action") or {}).get("kind") == "credential_store"
    )
    fields = _walk(store_form, lambda c: c.type == "field")
    by_name = {f.props.get("name"): f.props for f in fields}
    assert "description" in by_name
    assert by_name["description"].get("type") == "text"


async def test_vault_form_heading_mentions_rotation(test_db):
    """Vault add form heading says '자격증명 추가 / 회전' (rotation visible)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    headings = _walk(spec.root, lambda c: c.type == "heading")
    heading_values = [h.props.get("value", "") for h in headings]
    assert any("회전" in v for v in heading_values)


async def test_vault_form_has_rotation_explanation_text(test_db):
    """Vault card contains explanatory text about rotation (overwriting same ID)."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("교체" in v or "회전" in v for v in text_values)


async def test_vault_card_description_text_mentions_grouping(test_db):
    """The vault card description mentions grouping."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("그룹" in v for v in text_values)


# ---------------------------------------------------------------------------
# Existing state preservation
# ---------------------------------------------------------------------------

async def test_vault_card_empty_state_still_works(test_db):
    """Empty state message still present when no entries exist."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("저장된 자격증명이 없습니다" in v for v in text_values)


async def test_vault_card_unavailable_state_still_works(test_db):
    """Unavailable state still shown when db lacks list_settings_by_prefix."""
    store = _FakeStoreNoList()
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    texts = _walk(spec.root, lambda c: c.type == "text")
    text_values = [t.props.get("value", "") for t in texts]
    assert any("자격증명 금고를 불러올 수 없습니다" in v for v in text_values)


async def test_vault_card_heading_still_present(test_db):
    """'자격증명 금고' heading always renders."""
    store = _FakeStoreAdmin(vault_keys=[], vault_data={})
    spec = await settings_view.build(store, settings_store=store, user_id="admin")
    headings = _walk(spec.root, lambda c: c.type == "heading")
    heading_values = [h.props.get("value", "") for h in headings]
    assert any("자격증명 금고" in v for v in heading_values)
