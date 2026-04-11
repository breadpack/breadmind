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


_SERVER_A = {
    "name": "github",
    "command": "npx",
    "args": ["-y", "github-mcp"],
    "env": {},
    "enabled": True,
}
_SERVER_B = {
    "name": "local",
    "command": "python",
    "args": ["-m", "local"],
    "env": {},
    "enabled": False,
}


async def test_append_adds_item_to_list(deps):
    deps["store"].data["mcp_servers"] = [_SERVER_A]
    svc = build(deps)
    result = await svc.append("mcp_servers", _SERVER_B, actor="agent:core")
    assert result.ok is True
    assert result.operation == "append"
    assert len(deps["store"].data["mcp_servers"]) == 2
    assert deps["store"].data["mcp_servers"][1]["name"] == "local"


async def test_append_validates_merged_list(deps):
    deps["store"].data["mcp_servers"] = []
    svc = build(deps)
    # Missing "command" — schema should reject.
    result = await svc.append(
        "mcp_servers", {"name": "bad"}, actor="agent:core"
    )
    assert result.ok is False
    assert "validation failed" in (result.error or "")
    assert deps["store"].data["mcp_servers"] == []


async def test_update_item_patches_matching_entry(deps):
    deps["store"].data["mcp_servers"] = [_SERVER_A, _SERVER_B]
    svc = build(deps)
    result = await svc.update_item(
        "mcp_servers",
        match_field="name",
        match_value="github",
        patch={"enabled": False},
        actor="agent:core",
    )
    assert result.ok is True
    assert result.operation == "update_item"
    updated = deps["store"].data["mcp_servers"][0]
    assert updated["enabled"] is False
    assert updated["name"] == "github"  # unchanged


async def test_update_item_unknown_match_returns_error(deps):
    deps["store"].data["mcp_servers"] = [_SERVER_A]
    svc = build(deps)
    result = await svc.update_item(
        "mcp_servers",
        match_field="name",
        match_value="nope",
        patch={"enabled": False},
        actor="agent:core",
    )
    assert result.ok is False
    assert "no matching item" in (result.error or "").lower()


async def test_delete_item_removes_matching_entry(deps):
    deps["store"].data["mcp_servers"] = [_SERVER_A, _SERVER_B]
    svc = build(deps)
    result = await svc.delete_item(
        "mcp_servers",
        match_field="name",
        match_value="github",
        actor="agent:core",
    )
    assert result.ok is True
    assert result.operation == "delete_item"
    assert result.persisted is True
    remaining = deps["store"].data["mcp_servers"]
    assert len(remaining) == 1
    assert remaining[0]["name"] == "local"
    # Audit content: dedicated kind, and old_preview captures the pre-mutation list.
    entry = deps["audit"].entries[-1]
    assert entry["kind"] == "settings_delete_item"
    assert len(entry["old_preview"]) == 2
    assert len(entry["new_preview"]) == 1


async def test_set_credential_stores_in_vault(deps):
    svc = build(deps)
    result = await svc.set_credential(
        "apikey:anthropic",
        "sk-ant-xxxxxxxxxxxx",
        description="primary account",
        actor="agent:core",
    )
    assert result.ok is True
    assert result.operation == "credential_store"
    assert result.key == "apikey:anthropic"
    assert len(deps["vault"].store_calls) == 1
    cred_id, value, metadata = deps["vault"].store_calls[0]
    assert cred_id == "apikey:anthropic"
    assert value == "sk-ant-xxxxxxxxxxxx"
    assert metadata == {"description": "primary account"}
    assert len(deps["audit"].entries) == 1
    entry = deps["audit"].entries[0]
    # Audit never carries the plaintext.
    assert "sk-ant" not in str(entry)
    assert entry["kind"] == "credential_store"


async def test_set_credential_rejects_non_credential_key(deps):
    svc = build(deps)
    result = await svc.set_credential(
        "persona", "sk-ant-xxxxxxxxxxxx", actor="agent:core"
    )
    assert result.ok is False
    assert "not a credential key" in (result.error or "").lower()
    assert deps["vault"].store_calls == []


async def test_delete_credential_removes_from_vault(deps):
    svc = build(deps)
    result = await svc.delete_credential("apikey:anthropic", actor="agent:core")
    assert result.ok is True
    assert result.operation == "credential_delete"
    assert deps["vault"].delete_calls == ["apikey:anthropic"]
