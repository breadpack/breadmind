from breadmind.settings.approval_queue import PendingApprovalQueue
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
    def __init__(self):
        self.stored = []
    async def store(self, cred_id, value, metadata=None):
        self.stored.append((cred_id, value))
        return cred_id
    async def delete(self, cred_id):
        return True


async def _noop(**kwargs):
    return 1


def make_service():
    return SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop,
        reload_registry=SettingsReloadRegistry(),
        approval_queue=PendingApprovalQueue(),
    )


async def test_credential_write_requires_approval_for_agent_actor():
    svc = make_service()
    result = await svc.set_credential(
        "apikey:anthropic", "sk-ant-xxx", actor="agent:core"
    )
    assert result.ok is False
    assert result.pending_approval_id is not None
    assert result.persisted is False
    assert "PENDING" in result.summary()


async def test_credential_write_user_actor_bypasses_approval():
    svc = make_service()
    result = await svc.set_credential(
        "apikey:anthropic", "sk-ant-xxx", actor="user:alice"
    )
    assert result.ok is True
    assert result.pending_approval_id is None


async def test_admin_key_write_requires_approval_for_agent_actor():
    svc = make_service()
    result = await svc.set(
        "safety_blacklist", ["rm -rf /"], actor="agent:core"
    )
    assert result.ok is False
    assert result.pending_approval_id is not None


async def test_approving_pending_write_executes_it():
    svc = make_service()
    result = await svc.set_credential(
        "apikey:anthropic", "sk-ant-xxx", actor="agent:core"
    )
    pending_id = result.pending_approval_id
    assert pending_id

    resolved = await svc.resolve_approval(pending_id)
    assert resolved.ok is True
    assert resolved.persisted is True


async def test_unknown_approval_id_returns_error():
    svc = make_service()
    result = await svc.resolve_approval("nonexistent")
    assert result.ok is False
    assert "unknown" in (result.error or "").lower()
