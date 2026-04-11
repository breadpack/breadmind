import pytest

from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService


class FakeStore:
    def __init__(self, data=None):
        self.data = dict(data or {})

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value

    async def delete_setting(self, key):
        self.data.pop(key, None)


class FakeVault:
    def __init__(self):
        self.store_calls = []
        self.delete_calls = []

    async def store(self, cred_id, value, metadata=None):
        self.store_calls.append((cred_id, value, metadata))
        return cred_id

    async def retrieve(self, cred_id):
        return None

    async def delete(self, cred_id):
        self.delete_calls.append(cred_id)
        return True

    async def list_ids(self, prefix=""):
        return []


class AuditCollector:
    def __init__(self):
        self.entries = []

    async def record(self, **kwargs):
        self.entries.append(kwargs)
        return len(self.entries)


@pytest.fixture
def deps():
    return {
        "store": FakeStore({"persona": {"preset": "professional"}}),
        "vault": FakeVault(),
        "audit": AuditCollector(),
        "registry": SettingsReloadRegistry(),
    }


def build(deps):
    return SettingsService(
        store=deps["store"],
        vault=deps["vault"],
        audit_sink=deps["audit"].record,
        reload_registry=deps["registry"],
    )


async def test_get_returns_store_value(deps):
    svc = build(deps)
    assert await svc.get("persona") == {"preset": "professional"}


async def test_get_unknown_key_returns_none(deps):
    svc = build(deps)
    assert await svc.get("monitoring_config") is None


async def test_get_credential_returns_masked_placeholder(deps):
    svc = build(deps)
    assert await svc.get("apikey:anthropic") == "●●●●"


async def test_set_rejects_unknown_key(deps):
    svc = build(deps)
    result = await svc.set("not_a_real_key", "x", actor="agent:core")
    assert result.ok is False
    assert "not allowed" in (result.error or "").lower()
    assert deps["store"].data.get("not_a_real_key") is None


async def test_set_rejects_invalid_value(deps):
    svc = build(deps)
    result = await svc.set("persona", 42, actor="agent:core")
    assert result.ok is False
    assert result.persisted is False
    # Value unchanged.
    assert deps["store"].data["persona"] == {"preset": "professional"}


async def test_set_persists_and_audits(deps):
    svc = build(deps)
    result = await svc.set(
        "persona", {"preset": "friendly"}, actor="agent:core"
    )
    assert result.ok is True
    assert result.persisted is True
    assert result.operation == "set"
    assert result.key == "persona"
    assert result.restart_required is False
    assert deps["store"].data["persona"] == {"preset": "friendly"}
    assert len(deps["audit"].entries) == 1
    entry = deps["audit"].entries[0]
    assert entry["kind"] == "settings_write"
    assert entry["key"] == "persona"
    assert entry["actor"] == "agent:core"


async def test_set_embedding_config_flags_restart_required(deps):
    svc = build(deps)
    result = await svc.set(
        "embedding_config",
        {"provider": "openai", "model": "text-embedding-3-small", "dimensions": 1536},
        actor="agent:core",
    )
    assert result.ok is True
    assert result.restart_required is True
