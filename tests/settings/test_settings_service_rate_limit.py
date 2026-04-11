from breadmind.settings.rate_limiter import SlidingWindowRateLimiter
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService


class FakeStore:
    def __init__(self):
        self.data = {"persona": {"preset": "professional"}}
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


async def _noop(**kwargs):
    return 1


def _build(limiter):
    return SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop,
        reload_registry=SettingsReloadRegistry(),
        rate_limiter=limiter,
    )


def test_limiter_blocks_after_window_cap():
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_events=2)
    now = 1000.0
    assert limiter.check("agent:core", now=now) is True
    assert limiter.check("agent:core", now=now + 1) is True
    assert limiter.check("agent:core", now=now + 2) is False
    # After window rolls past the first event, one slot frees.
    assert limiter.check("agent:core", now=now + 61) is True


async def test_settings_service_respects_rate_limiter():
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_events=1)
    svc = _build(limiter)
    r1 = await svc.set("persona", {"preset": "friendly"}, actor="agent:core")
    assert r1.ok is True
    r2 = await svc.set("persona", {"preset": "concise"}, actor="agent:core")
    assert r2.ok is False
    assert "rate limit" in (r2.error or "").lower()


async def test_user_actor_exempt_from_rate_limit():
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_events=1)
    svc = _build(limiter)
    await svc.set("persona", {"preset": "friendly"}, actor="user:alice")
    r = await svc.set("persona", {"preset": "concise"}, actor="user:alice")
    assert r.ok is True
