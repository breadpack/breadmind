"""Tests for credential_store and credential_delete SDUI actions (Phase 5)."""
import pytest

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.actions import ActionHandler


class FakeStore:
    def __init__(self, initial=None):
        self.data: dict = dict(initial or {})

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value


class FakeVault:
    def __init__(self):
        self._store: dict = {}

    async def store(self, credential_id, value, metadata=None):
        self._store[credential_id] = {"value": value, "metadata": metadata}
        return credential_id

    async def retrieve(self, credential_id):
        entry = self._store.get(credential_id)
        return entry["value"] if entry else None

    async def delete(self, credential_id):
        if credential_id not in self._store:
            return False
        del self._store[credential_id]
        return True

    async def exists(self, credential_id):
        return credential_id in self._store

    async def list_ids(self, prefix=""):
        return [k for k in self._store if k.startswith(prefix)]


@pytest.fixture
async def bus(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        yield bus
    finally:
        await bus.stop()


def make_handler(bus, *, admin_user="alice", vault=None):
    """Build an ActionHandler with the given admin and vault."""
    store = FakeStore(
        {"safety_permissions": {"admin_users": [admin_user]}} if admin_user else {}
    )
    return ActionHandler(bus=bus, settings_store=store, credential_vault=vault)


# ---------------------------------------------------------------------------
# credential_store — positive
# ---------------------------------------------------------------------------

async def test_credential_store_success(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert result["credential_id"] == "ssh:prod"
    assert result["refresh_view"] == "settings_view"
    assert await vault.retrieve("ssh:prod") == "s3cr3t"


async def test_credential_store_with_metadata(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    meta = {"description": "Production SSH key"}
    result = await handler.handle(
        {
            "kind": "credential_store",
            "credential_id": "ssh:prod",
            "value": "s3cr3t",
            "metadata": meta,
        },
        user_id="alice",
    )
    assert result["ok"] is True
    assert vault._store["ssh:prod"]["metadata"] == meta


async def test_credential_store_overwrites_existing(bus):
    vault = FakeVault()
    vault._store["ssh:prod"] = {"value": "old", "metadata": None}
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "new"},
        user_id="alice",
    )
    assert result["ok"] is True
    assert await vault.retrieve("ssh:prod") == "new"


# ---------------------------------------------------------------------------
# credential_delete — positive
# ---------------------------------------------------------------------------

async def test_credential_delete_success(bus):
    vault = FakeVault()
    vault._store["ssh:prod"] = {"value": "s3cr3t", "metadata": None}
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_delete", "credential_id": "ssh:prod"},
        user_id="alice",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert result["credential_id"] == "ssh:prod"
    assert result["refresh_view"] == "settings_view"
    assert "ssh:prod" not in vault._store


# ---------------------------------------------------------------------------
# Vault not configured
# ---------------------------------------------------------------------------

async def test_credential_store_vault_not_configured(bus):
    handler = make_handler(bus, vault=None)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "vault" in result["error"].lower()


async def test_credential_delete_vault_not_configured(bus):
    handler = make_handler(bus, vault=None)
    result = await handler.handle(
        {"kind": "credential_delete", "credential_id": "ssh:prod"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "vault" in result["error"].lower()


# ---------------------------------------------------------------------------
# credential_store — validation: credential_id
# ---------------------------------------------------------------------------

async def test_credential_store_missing_credential_id(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "credential_id" in result["error"].lower()


async def test_credential_store_empty_credential_id(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "credential_id" in result["error"].lower()


async def test_credential_store_invalid_chars_in_credential_id(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "bad id!", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "credential_id" in result["error"].lower()


async def test_credential_store_credential_id_too_long(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    long_id = "a" * 129
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": long_id, "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "credential_id" in result["error"].lower()


async def test_credential_store_credential_id_max_length_accepted(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    max_id = "a" * 128
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": max_id, "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is True


async def test_credential_store_credential_id_all_valid_chars(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {
            "kind": "credential_store",
            "credential_id": "abc:123_DEF.xyz@host-name/path",
            "value": "s3cr3t",
        },
        user_id="alice",
    )
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# credential_store — validation: value
# ---------------------------------------------------------------------------

async def test_credential_store_empty_value(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": ""},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "value" in result["error"].lower()


async def test_credential_store_missing_value(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "value" in result["error"].lower()


async def test_credential_store_oversized_value(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    big_value = "x" * (64 * 1024 + 1)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": big_value},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "value" in result["error"].lower()


async def test_credential_store_value_at_max_size_accepted(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    max_value = "x" * (64 * 1024)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": max_value},
        user_id="alice",
    )
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# credential_store — validation: metadata
# ---------------------------------------------------------------------------

async def test_credential_store_metadata_not_dict(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {
            "kind": "credential_store",
            "credential_id": "ssh:prod",
            "value": "s3cr3t",
            "metadata": ["not", "a", "dict"],
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "metadata" in result["error"].lower()


async def test_credential_store_metadata_none_is_ok(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is True
    assert vault._store["ssh:prod"]["metadata"] is None


# ---------------------------------------------------------------------------
# credential_delete — not found
# ---------------------------------------------------------------------------

async def test_credential_delete_not_found(bus):
    vault = FakeVault()
    handler = make_handler(bus, vault=vault)
    result = await handler.handle(
        {"kind": "credential_delete", "credential_id": "ssh:nonexistent"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


# ---------------------------------------------------------------------------
# Admin gating
# ---------------------------------------------------------------------------

async def test_credential_store_non_admin_rejected(bus):
    vault = FakeVault()
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store, credential_vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="bob",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()
    assert "admin" in result["error"].lower()


async def test_credential_delete_non_admin_rejected(bus):
    vault = FakeVault()
    vault._store["ssh:prod"] = {"value": "s3cr3t", "metadata": None}
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store, credential_vault=vault)
    result = await handler.handle(
        {"kind": "credential_delete", "credential_id": "ssh:prod"},
        user_id="bob",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()
    assert "ssh:prod" in vault._store  # not deleted


async def test_credential_store_admin_succeeds(bus):
    vault = FakeVault()
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store, credential_vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Bootstrap: empty admin_users still blocks vault actions (no bootstrap exception)
# ---------------------------------------------------------------------------

async def test_credential_store_no_admin_users_blocks_store(bus):
    """Vault actions must NOT have a bootstrap exception — always require admin."""
    vault = FakeVault()
    store = FakeStore()  # no safety_permissions at all
    handler = ActionHandler(bus=bus, settings_store=store, credential_vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()


async def test_credential_delete_no_admin_users_blocks_delete(bus):
    """Vault actions must NOT have a bootstrap exception — always require admin."""
    vault = FakeVault()
    vault._store["ssh:prod"] = {"value": "s3cr3t", "metadata": None}
    store = FakeStore()  # no safety_permissions at all
    handler = ActionHandler(bus=bus, settings_store=store, credential_vault=vault)
    result = await handler.handle(
        {"kind": "credential_delete", "credential_id": "ssh:prod"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "permission denied" in result["error"].lower()
    assert "ssh:prod" in vault._store  # not deleted


# ---------------------------------------------------------------------------
# Unknown action kind (sanity check)
# ---------------------------------------------------------------------------

async def test_unknown_action_kind_returns_error(bus):
    handler = make_handler(bus, vault=FakeVault())
    result = await handler.handle(
        {"kind": "credential_list"},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "unknown" in result["error"].lower()
