from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService


class FakeStore:
    def __init__(self):
        self.data = {}

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value

    async def delete_setting(self, key):
        self.data.pop(key, None)


class FakeVault:
    async def store(self, *a, **k):
        return "x"

    async def delete(self, *a, **k):
        return True


class AuditCollector:
    def __init__(self):
        self.entries = []

    async def record(self, **kwargs):
        self.entries.append(kwargs)
        return len(self.entries)


def _build():
    audit = AuditCollector()
    svc = SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=audit.record,
        reload_registry=SettingsReloadRegistry(),
    )
    return svc, audit


async def test_set_audit_key_override_changes_audit_row_not_storage():
    svc, audit = _build()
    result = await svc.set(
        "safety_permissions",
        {"admin_users": ["alice"], "user_permissions": {}},
        actor="user:alice",
        audit_key="safety_permissions_admin_users",
        audit_kind="settings_append",
    )
    assert result.ok is True
    # Real storage still uses the schema key.
    assert svc._store.data["safety_permissions"] == {
        "admin_users": ["alice"],
        "user_permissions": {},
    }
    # Audit row reflects the SDUI-facing key/kind.
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry["kind"] == "settings_append"
    assert entry["key"] == "safety_permissions_admin_users"


async def test_set_without_overrides_uses_storage_key():
    svc, audit = _build()
    result = await svc.set(
        "persona",
        {"preset": "friendly"},
        actor="user:alice",
    )
    assert result.ok is True
    assert audit.entries[0]["kind"] == "settings_write"
    assert audit.entries[0]["key"] == "persona"
