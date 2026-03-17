"""ServiceAdapter and AdapterRegistry unit tests."""
from datetime import datetime, timezone
import pytest


class FakeAdapter:
    def __init__(self, domain: str, source: str):
        self._domain = domain
        self._source = source

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def source(self) -> str:
        return self._source

    async def authenticate(self, credentials):
        return True
    async def list_items(self, filters=None, limit=50):
        return []
    async def get_item(self, source_id):
        return None
    async def create_item(self, entity):
        return "fake-id"
    async def update_item(self, source_id, changes):
        return True
    async def delete_item(self, source_id):
        return True
    async def sync(self, since=None):
        from breadmind.personal.adapters.base import SyncResult
        return SyncResult(created=[], updated=[], deleted=[], errors=[], synced_at=datetime.now(timezone.utc))


def test_sync_result_creation():
    from breadmind.personal.adapters.base import SyncResult
    now = datetime.now(timezone.utc)
    result = SyncResult(created=["a"], updated=["b"], deleted=[], errors=[], synced_at=now)
    assert result.created == ["a"]
    assert result.errors == []


def test_registry_register_and_get():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()
    adapter = FakeAdapter("task", "builtin")
    registry.register(adapter)
    found = registry.get_adapter("task", "builtin")
    assert found is adapter


def test_registry_get_missing_raises():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()
    with pytest.raises(KeyError):
        registry.get_adapter("task", "nonexistent")


def test_registry_list_by_domain():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()
    a1 = FakeAdapter("task", "builtin")
    a2 = FakeAdapter("task", "jira")
    a3 = FakeAdapter("event", "builtin")
    registry.register(a1)
    registry.register(a2)
    registry.register(a3)
    task_adapters = registry.list_adapters("task")
    assert len(task_adapters) == 2
    all_adapters = registry.list_adapters()
    assert len(all_adapters) == 3


def test_registry_duplicate_replaces():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()
    a1 = FakeAdapter("task", "builtin")
    a2 = FakeAdapter("task", "builtin")
    registry.register(a1)
    registry.register(a2)
    assert registry.get_adapter("task", "builtin") is a2
