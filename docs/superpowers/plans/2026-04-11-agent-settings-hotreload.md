# Agent Settings Hot-Reload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add built-in `breadmind_*_setting` agent tools wired through a new `SettingsService` facade and `SettingsReloadRegistry`, so CoreAgent can read/modify every BreadMind runtime setting and have changes take effect immediately without a process restart.

**Architecture:** Introduce a validate→authorize→store→audit→emit pipeline (`SettingsService`) shared by `ActionHandler` (UI path) and new `@tool` wrappers (agent path). Each long-lived component subscribes to `SETTINGS_CHANGED` via `SettingsReloadRegistry` with its own reload function; all hot-reloadable keys from `settings_schema.py` are covered, leaving only `embedding_config` requiring restart.

**Tech Stack:** Python 3.12+, asyncio, pytest-asyncio (auto mode), existing EventBus, FileSettingsStore, CredentialVault, SDUI actions.

**Spec:** `docs/superpowers/specs/2026-04-11-agent-settings-hotreload-design.md`

---

## File Structure

**New modules:**
- `src/breadmind/settings/__init__.py` — package marker, exports public API
- `src/breadmind/settings/reload_registry.py` — `SettingsReloadRegistry`, `DispatchResult`
- `src/breadmind/settings/service.py` — `SettingsService`, `SetResult`, `PendingApproval`
- `src/breadmind/settings/approval_queue.py` — `PendingApprovalQueue` for deferred writes
- `src/breadmind/settings/rate_limiter.py` — `SlidingWindowRateLimiter` (per-actor)
- `src/breadmind/settings/llm_holder.py` — `LLMProviderHolder` (transparent proxy)
- `src/breadmind/tools/settings_tools.py` — 8 `@tool` functions
- `src/breadmind/tools/settings_tool_registration.py` — entry point that binds tools to a ToolRegistry with an injected SettingsService

**Modified modules:**
- `src/breadmind/core/events.py` — add `EventType.SETTINGS_CHANGED`
- `src/breadmind/sdui/actions.py` — delegate 5 settings action kinds into `SettingsService`
- `src/breadmind/core/agent.py` — CoreAgent accepts `LLMProviderHolder`; exposes `reload_prompt_components()`
- `src/breadmind/core/safety_guard.py` — `reload(new_config)` hook
- `src/breadmind/web/routes/ui.py` — construct `SettingsService` + registry in `_ensure_projector`, wire subscribers, register agent tools

**Test files:**
- `tests/settings/test_reload_registry.py`
- `tests/settings/test_settings_service.py`
- `tests/settings/test_settings_service_events.py`
- `tests/settings/test_settings_service_approval.py`
- `tests/settings/test_settings_service_rate_limit.py`
- `tests/settings/test_llm_holder.py`
- `tests/tools/test_settings_tools.py`
- `tests/tools/test_settings_tools_e2e.py`
- `tests/settings/test_llm_reloader.py`
- `tests/settings/test_persona_reloader.py`
- `tests/settings/test_safety_reloader.py`
- `tests/settings/test_runtime_reloader.py`
- `tests/settings/test_mcp_reloader.py`
- `tests/sdui/test_settings_actions_facade.py` — integration proof that existing SDUI suite stays green through the refactor

---

## Conventions

All tests use `pytest-asyncio` auto mode: async test functions need no decorator. Test DB fixture is `test_db` from `tests/conftest.py`; tests that do not need a real DB use in-memory fakes. Every task ends with a commit. Commit messages follow `type(scope): subject` style seen in recent commits (e.g. `feat(settings): ...`, `refactor(sdui): ...`, `test(settings): ...`).

**Shared type fixtures used throughout the plan:**

```python
# SetResult — returned by every SettingsService write method
from dataclasses import dataclass, field
from typing import Any

@dataclass
class SetResult:
    ok: bool
    operation: str                # "set" | "append" | "update_item" | "delete_item" | "credential_store" | "credential_delete"
    key: str
    persisted: bool
    hot_reloaded: bool
    restart_required: bool
    reload_errors: dict[str, str] = field(default_factory=dict)
    audit_id: int | None = None
    pending_approval_id: str | None = None
    error: str | None = None
```

```python
# DispatchResult — returned by SettingsReloadRegistry.dispatch
@dataclass
class DispatchResult:
    all_ok: bool
    ran: list[str]                # pattern strings that matched and ran
    errors: dict[str, str]        # pattern → error message
```

---

## Task 1: Event infra — SETTINGS_CHANGED + SettingsReloadRegistry

**Files:**
- Modify: `src/breadmind/core/events.py` (add enum member)
- Create: `src/breadmind/settings/__init__.py`
- Create: `src/breadmind/settings/reload_registry.py`
- Test: `tests/settings/test_reload_registry.py`

- [ ] **Step 1: Add SETTINGS_CHANGED to EventType**

Open `src/breadmind/core/events.py` and locate the `EventType` enum. Add one member after `APPROVAL_REQUESTED`:

```python
class EventType(str, Enum):
    # ... existing members ...
    APPROVAL_REQUESTED = "approval_requested"
    SETTINGS_CHANGED = "settings_changed"
    PROGRESS = "progress"
```

- [ ] **Step 2: Create settings package marker**

Create `src/breadmind/settings/__init__.py`:

```python
"""Runtime settings facade and hot-reload plumbing."""

from breadmind.settings.reload_registry import (
    DispatchResult,
    SettingsReloadRegistry,
)

__all__ = ["DispatchResult", "SettingsReloadRegistry"]
```

- [ ] **Step 3: Write the failing registry test**

Create `tests/settings/test_reload_registry.py`:

```python
import asyncio
import pytest

from breadmind.settings.reload_registry import (
    DispatchResult,
    SettingsReloadRegistry,
)


async def test_exact_key_match_runs_reload_fn():
    registry = SettingsReloadRegistry()
    calls = []

    async def reload_llm(ctx):
        calls.append(ctx["new"])

    registry.register("llm", reload_llm)
    result = await registry.dispatch(
        key="llm", operation="set", old=None, new={"default_provider": "gemini"}
    )
    assert result.all_ok is True
    assert result.ran == ["llm"]
    assert calls == [{"default_provider": "gemini"}]


async def test_prefix_glob_matches_credential_keys():
    registry = SettingsReloadRegistry()
    calls = []

    async def reload_credential(ctx):
        calls.append(ctx["key"])

    registry.register("apikey:*", reload_credential)
    result = await registry.dispatch(
        key="apikey:anthropic", operation="credential_store", old=None, new=None
    )
    assert result.all_ok is True
    assert calls == ["apikey:anthropic"]


async def test_non_matching_key_runs_nothing():
    registry = SettingsReloadRegistry()
    registry.register("llm", lambda ctx: None)
    result = await registry.dispatch(
        key="persona", operation="set", old=None, new="friendly"
    )
    assert result.all_ok is True
    assert result.ran == []


async def test_failure_isolated_per_subscriber():
    registry = SettingsReloadRegistry()

    async def good(ctx):
        ctx["good"] = True

    async def bad(ctx):
        raise RuntimeError("boom")

    seen = {}
    async def probe(ctx):
        seen.update(ctx)

    registry.register("llm", good)
    registry.register("llm", bad)
    registry.register("llm", probe)

    result = await registry.dispatch(key="llm", operation="set", old=None, new={})
    assert result.all_ok is False
    assert "bad" in "".join(result.errors.keys()) or any(
        "boom" in v for v in result.errors.values()
    )
    # Both non-failing subscribers still ran.
    assert len(result.ran) == 3


async def test_sync_reload_fn_wrapped_in_thread():
    registry = SettingsReloadRegistry()
    calls = []

    def sync_reload(ctx):
        calls.append(ctx["key"])

    registry.register("persona", sync_reload)
    result = await registry.dispatch(
        key="persona", operation="set", old="a", new="b"
    )
    assert result.all_ok is True
    assert calls == ["persona"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/settings/test_reload_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'breadmind.settings.reload_registry'`

- [ ] **Step 5: Implement SettingsReloadRegistry**

Create `src/breadmind/settings/reload_registry.py`:

```python
"""Dispatches SETTINGS_CHANGED events to key-pattern subscribers.

Registering:
    registry.register("llm", reload_llm)
    registry.register("apikey:*", reload_credential)

Dispatching:
    result = await registry.dispatch(
        key="llm", operation="set", old={...}, new={...}
    )

Patterns:
    - Exact key (``"llm"``) matches only that key.
    - Prefix glob (``"apikey:*"``) matches any key starting with ``"apikey:"``.

Reload functions may be sync or async and must accept a single ``ctx`` dict
with fields ``key``, ``operation``, ``old``, ``new``. One failing subscriber
never blocks the others; the exception is captured in ``DispatchResult.errors``.
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ReloadFn = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass
class DispatchResult:
    all_ok: bool
    ran: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class SettingsReloadRegistry:
    def __init__(self) -> None:
        self._subs: list[tuple[str, ReloadFn]] = []

    def register(self, pattern: str, fn: ReloadFn) -> None:
        self._subs.append((pattern, fn))

    def _matches(self, pattern: str, key: str) -> bool:
        if pattern.endswith(":*"):
            return key.startswith(pattern[:-1])
        return pattern == key

    async def dispatch(
        self,
        *,
        key: str,
        operation: str,
        old: Any,
        new: Any,
    ) -> DispatchResult:
        matching = [(p, fn) for p, fn in self._subs if self._matches(p, key)]
        if not matching:
            return DispatchResult(all_ok=True)

        ctx = {"key": key, "operation": operation, "old": old, "new": new}

        async def _run(pattern: str, fn: ReloadFn) -> tuple[str, Exception | None]:
            try:
                if inspect.iscoroutinefunction(fn):
                    await fn(ctx)
                else:
                    await asyncio.to_thread(fn, ctx)
                return pattern, None
            except Exception as exc:  # noqa: BLE001
                return pattern, exc

        results = await asyncio.gather(*(_run(p, fn) for p, fn in matching))

        ran: list[str] = []
        errors: dict[str, str] = {}
        for pattern, exc in results:
            ran.append(pattern)
            if exc is not None:
                errors[pattern] = f"{type(exc).__name__}: {exc}"

        return DispatchResult(all_ok=not errors, ran=ran, errors=errors)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/settings/test_reload_registry.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/core/events.py src/breadmind/settings/__init__.py src/breadmind/settings/reload_registry.py tests/settings/test_reload_registry.py
git commit -m "feat(settings): add SETTINGS_CHANGED event + reload registry"
```

---

## Task 2: SettingsService — get/set with validation, routing, audit hook

**Files:**
- Create: `src/breadmind/settings/service.py`
- Test: `tests/settings/test_settings_service.py`

- [ ] **Step 1: Write the failing service test**

Create `tests/settings/test_settings_service.py`:

```python
import pytest

from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SetResult, SettingsService


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
        "store": FakeStore({"persona": "professional"}),
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
    assert await svc.get("persona") == "professional"


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
    assert deps["store"].data["persona"] == "professional"


async def test_set_persists_and_audits(deps):
    svc = build(deps)
    result = await svc.set(
        "persona", "friendly", actor="agent:core"
    )
    assert result.ok is True
    assert result.persisted is True
    assert result.operation == "set"
    assert result.key == "persona"
    assert result.restart_required is False
    assert deps["store"].data["persona"] == "friendly"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/settings/test_settings_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'breadmind.settings.service'`

- [ ] **Step 3: Implement SettingsService (get, set)**

Create `src/breadmind/settings/service.py`:

```python
"""Facade for runtime settings read/write with validation, audit, and hot reload.

``SettingsService`` is the one object that owns the settings write pipeline:
validate → authorize → persist → audit → dispatch reload subscribers. Both the
SDUI ``ActionHandler`` and the built-in agent tools go through it so every
write path produces the same side effects.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from breadmind.sdui import settings_schema
from breadmind.settings.reload_registry import DispatchResult, SettingsReloadRegistry

AuditSink = Callable[..., Awaitable[int | None]]


@dataclass
class SetResult:
    ok: bool
    operation: str
    key: str
    persisted: bool = False
    hot_reloaded: bool = False
    restart_required: bool = False
    reload_errors: dict[str, str] = field(default_factory=dict)
    audit_id: int | None = None
    pending_approval_id: str | None = None
    error: str | None = None

    def summary(self) -> str:
        if self.pending_approval_id is not None:
            return (
                f"PENDING: approval required for key={self.key}. "
                f"approval_id={self.pending_approval_id}. Ask the user to confirm."
            )
        if not self.ok:
            return f"ERROR: {self.error or 'unknown error'}"
        parts = [
            f"OK",
            f"key={self.key}",
            f"operation={self.operation}",
            f"hot_reloaded={str(self.hot_reloaded).lower()}",
            f"restart_required={str(self.restart_required).lower()}",
        ]
        if self.audit_id is not None:
            parts.append(f"audit_id={self.audit_id}")
        if self.reload_errors:
            parts.append(f"reload_errors={list(self.reload_errors.keys())}")
        return ". ".join(parts[:1]) + ". " + ", ".join(parts[1:])


class SettingsService:
    def __init__(
        self,
        *,
        store: Any,
        vault: Any,
        audit_sink: AuditSink,
        reload_registry: SettingsReloadRegistry,
    ) -> None:
        self._store = store
        self._vault = vault
        self._audit_sink = audit_sink
        self._registry = reload_registry
        self._key_locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._key_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._key_locks[key] = lock
        return lock

    async def get(self, key: str) -> Any:
        if settings_schema.is_credential_key(key):
            return "●●●●"
        return await self._store.get_setting(key)

    async def set(self, key: str, value: Any, *, actor: str) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(
                ok=False,
                operation="set",
                key=key,
                error=f"key '{key}' is not allowed",
            )
        try:
            normalized = settings_schema.validate_value(key, value)
        except settings_schema.SettingsValidationError as exc:
            return SetResult(
                ok=False,
                operation="set",
                key=key,
                error=f"validation failed — {exc}",
            )

        async with self._lock(key):
            old = await self._store.get_setting(key)
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_write",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="set", old=old, new=normalized
            )

        return SetResult(
            ok=True,
            operation="set",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/settings/test_settings_service.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/settings/service.py tests/settings/test_settings_service.py
git commit -m "feat(settings): add SettingsService facade with get/set"
```

---

## Task 3: SettingsService — append, update_item, delete_item

**Files:**
- Modify: `src/breadmind/settings/service.py`
- Test: append to `tests/settings/test_settings_service.py`

- [ ] **Step 1: Write failing tests for list operations**

Append to `tests/settings/test_settings_service.py`:

```python
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
    remaining = deps["store"].data["mcp_servers"]
    assert len(remaining) == 1
    assert remaining[0]["name"] == "local"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/settings/test_settings_service.py::test_append_adds_item_to_list tests/settings/test_settings_service.py::test_update_item_patches_matching_entry tests/settings/test_settings_service.py::test_delete_item_removes_matching_entry -v`
Expected: FAIL with `AttributeError: 'SettingsService' object has no attribute 'append'`

- [ ] **Step 3: Implement append, update_item, delete_item**

Append to `src/breadmind/settings/service.py` inside `SettingsService`:

```python
    async def append(self, key: str, item: Any, *, actor: str) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="append", key=key, error=f"key '{key}' is not allowed")

        async with self._lock(key):
            old = await self._store.get_setting(key) or []
            if not isinstance(old, list):
                return SetResult(
                    ok=False, operation="append", key=key,
                    error=f"key '{key}' is not a list",
                )
            merged = [*old, item]
            try:
                normalized = settings_schema.validate_value(key, merged)
            except settings_schema.SettingsValidationError as exc:
                return SetResult(
                    ok=False, operation="append", key=key,
                    error=f"validation failed — {exc}",
                )
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_append",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="append", old=old, new=normalized
            )

        return SetResult(
            ok=True,
            operation="append",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def update_item(
        self,
        key: str,
        *,
        match_field: str,
        match_value: Any,
        patch: dict[str, Any],
        actor: str,
    ) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="update_item", key=key, error=f"key '{key}' is not allowed")

        async with self._lock(key):
            old = await self._store.get_setting(key) or []
            if not isinstance(old, list):
                return SetResult(
                    ok=False, operation="update_item", key=key,
                    error=f"key '{key}' is not a list",
                )
            idx = next(
                (i for i, it in enumerate(old)
                 if isinstance(it, dict) and it.get(match_field) == match_value),
                None,
            )
            if idx is None:
                return SetResult(
                    ok=False, operation="update_item", key=key,
                    error=f"no matching item for {match_field}={match_value}",
                )
            new_list = [dict(it) for it in old]
            new_list[idx] = {**new_list[idx], **patch}
            try:
                normalized = settings_schema.validate_value(key, new_list)
            except settings_schema.SettingsValidationError as exc:
                return SetResult(
                    ok=False, operation="update_item", key=key,
                    error=f"validation failed — {exc}",
                )
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_update_item",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="update_item", old=old, new=normalized
            )

        return SetResult(
            ok=True,
            operation="update_item",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def delete_item(
        self,
        key: str,
        *,
        match_field: str,
        match_value: Any,
        actor: str,
    ) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="delete_item", key=key, error=f"key '{key}' is not allowed")

        async with self._lock(key):
            old = await self._store.get_setting(key) or []
            if not isinstance(old, list):
                return SetResult(
                    ok=False, operation="delete_item", key=key,
                    error=f"key '{key}' is not a list",
                )
            new_list = [
                it for it in old
                if not (isinstance(it, dict) and it.get(match_field) == match_value)
            ]
            if len(new_list) == len(old):
                return SetResult(
                    ok=False, operation="delete_item", key=key,
                    error=f"no matching item for {match_field}={match_value}",
                )
            try:
                normalized = settings_schema.validate_value(key, new_list)
            except settings_schema.SettingsValidationError as exc:
                return SetResult(
                    ok=False, operation="delete_item", key=key,
                    error=f"validation failed — {exc}",
                )
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind="settings_delete_item",
                key=key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="delete_item", old=old, new=normalized
            )

        return SetResult(
            ok=True,
            operation="delete_item",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=settings_schema.requires_restart(key),
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/settings/test_settings_service.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/settings/service.py tests/settings/test_settings_service.py
git commit -m "feat(settings): add append/update_item/delete_item to SettingsService"
```

---

## Task 4: SettingsService — credential methods

**Files:**
- Modify: `src/breadmind/settings/service.py`
- Test: append to `tests/settings/test_settings_service.py`

- [ ] **Step 1: Write failing credential tests**

Append to `tests/settings/test_settings_service.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/settings/test_settings_service.py::test_set_credential_stores_in_vault -v`
Expected: FAIL with `AttributeError: 'SettingsService' object has no attribute 'set_credential'`

- [ ] **Step 3: Implement credential methods**

Append to `SettingsService` in `src/breadmind/settings/service.py`:

```python
    async def set_credential(
        self,
        key: str,
        value: str,
        *,
        actor: str,
        description: str = "",
    ) -> SetResult:
        if not settings_schema.is_credential_key(key):
            return SetResult(
                ok=False,
                operation="credential_store",
                key=key,
                error=f"key '{key}' is not a credential key",
            )
        metadata: dict[str, Any] = {}
        if description:
            metadata["description"] = description

        async with self._lock(key):
            await self._vault.store(key, value, metadata or None)
            audit_id = await self._audit_sink(
                kind="credential_store",
                key=key,
                actor=actor,
                old_preview=None,
                new_preview=None,
            )
            # Credentials never carry plaintext through events.
            dispatch = await self._registry.dispatch(
                key=key, operation="credential_store", old=None, new=None
            )

        return SetResult(
            ok=True,
            operation="credential_store",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=False,
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )

    async def delete_credential(self, key: str, *, actor: str) -> SetResult:
        if not settings_schema.is_credential_key(key):
            return SetResult(
                ok=False,
                operation="credential_delete",
                key=key,
                error=f"key '{key}' is not a credential key",
            )
        async with self._lock(key):
            await self._vault.delete(key)
            audit_id = await self._audit_sink(
                kind="credential_delete",
                key=key,
                actor=actor,
                old_preview=None,
                new_preview=None,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="credential_delete", old=None, new=None
            )
        return SetResult(
            ok=True,
            operation="credential_delete",
            key=key,
            persisted=True,
            hot_reloaded=dispatch.all_ok,
            restart_required=False,
            reload_errors=dict(dispatch.errors),
            audit_id=audit_id,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/settings/test_settings_service.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/settings/service.py tests/settings/test_settings_service.py
git commit -m "feat(settings): add credential methods to SettingsService"
```

---

## Task 5: SettingsService — event bus emission

**Files:**
- Modify: `src/breadmind/settings/service.py`
- Test: `tests/settings/test_settings_service_events.py`

- [ ] **Step 1: Write failing event emission test**

Create `tests/settings/test_settings_service_events.py`:

```python
from breadmind.core.events import EventBus, EventType
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService


class FakeStore:
    def __init__(self):
        self.data = {"persona": "professional"}

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value

    async def delete_setting(self, key):
        self.data.pop(key, None)


class FakeVault:
    async def store(self, cred_id, value, metadata=None):
        return cred_id

    async def delete(self, cred_id):
        return True


async def _noop_audit(**kwargs):
    return 1


async def test_set_emits_settings_changed_event():
    bus = EventBus()
    events: list[dict] = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    svc = SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=bus,
    )

    result = await svc.set("persona", "friendly", actor="agent:core")
    assert result.ok
    assert len(events) == 1
    ev = events[0]
    assert ev["key"] == "persona"
    assert ev["operation"] == "set"
    assert ev["old"] == "professional"
    assert ev["new"] == "friendly"
    assert ev["actor"] == "agent:core"


async def test_credential_event_masks_plaintext():
    bus = EventBus()
    events: list[dict] = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    svc = SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=bus,
    )

    await svc.set_credential(
        "apikey:anthropic", "sk-ant-secret", actor="agent:core"
    )
    assert len(events) == 1
    assert events[0]["old"] is None
    assert events[0]["new"] is None
    # Plaintext never reaches the bus.
    assert "sk-ant-secret" not in str(events[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/settings/test_settings_service_events.py -v`
Expected: FAIL with `TypeError: SettingsService.__init__() got an unexpected keyword argument 'event_bus'`

- [ ] **Step 3: Add event bus emission**

Modify `src/breadmind/settings/service.py`:

Update `SettingsService.__init__` to accept `event_bus`:

```python
    def __init__(
        self,
        *,
        store: Any,
        vault: Any,
        audit_sink: AuditSink,
        reload_registry: SettingsReloadRegistry,
        event_bus: Any | None = None,
    ) -> None:
        self._store = store
        self._vault = vault
        self._audit_sink = audit_sink
        self._registry = reload_registry
        self._bus = event_bus
        self._key_locks: dict[str, asyncio.Lock] = {}
```

Add a helper and call it from every write method after `dispatch` runs:

```python
    async def _emit(
        self,
        *,
        key: str,
        operation: str,
        old: Any,
        new: Any,
        actor: str,
        audit_id: int | None,
    ) -> None:
        if self._bus is None:
            return
        from breadmind.core.events import EventType
        if settings_schema.is_credential_key(key):
            old_payload = None
            new_payload = None
        else:
            old_payload = old
            new_payload = new
        await self._bus.async_emit(
            EventType.SETTINGS_CHANGED.value,
            {
                "key": key,
                "operation": operation,
                "old": old_payload,
                "new": new_payload,
                "actor": actor,
                "audit_id": audit_id,
            },
        )
```

In each of `set`, `append`, `update_item`, `delete_item`, `set_credential`, `delete_credential`, call `await self._emit(...)` **inside** the `async with self._lock(key):` block, immediately after `dispatch = await self._registry.dispatch(...)`. Example for `set`:

```python
            dispatch = await self._registry.dispatch(
                key=key, operation="set", old=old, new=normalized
            )
            await self._emit(
                key=key, operation="set", old=old, new=normalized,
                actor=actor, audit_id=audit_id,
            )
```

Repeat the analogous `_emit` call in the other five methods, using the same `operation` string each method already passes to `dispatch`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/settings/test_settings_service_events.py tests/settings/test_settings_service.py -v`
Expected: all previous 15 + 2 new = 17 passed

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/settings/service.py tests/settings/test_settings_service_events.py
git commit -m "feat(settings): emit SETTINGS_CHANGED on every write path"
```

---

## Task 6: Refactor ActionHandler to delegate into SettingsService

**Files:**
- Modify: `src/breadmind/sdui/actions.py`
- Test: `tests/sdui/test_settings_actions_facade.py` + run the entire existing SDUI suite

This is a risky refactor. The success criterion is that every pre-existing SDUI test continues to pass with no assertion changes.

- [ ] **Step 1: Capture baseline — run the entire SDUI test suite**

Run: `python -m pytest tests/sdui/ -v --tb=short`
Expected: 542 passed (or the current number). Record the exact count for comparison after refactor.

- [ ] **Step 2: Write a delegation proof test**

Create `tests/sdui/test_settings_actions_facade.py`:

```python
from breadmind.core.events import EventBus, EventType
from breadmind.sdui.actions import ActionHandler


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
        self.store_calls = []
        self.delete_calls = []

    async def store(self, cred_id, value, metadata=None):
        self.store_calls.append((cred_id, value, metadata))
        return cred_id

    async def delete(self, cred_id):
        self.delete_calls.append(cred_id)
        return True


class FakeBus:
    async def async_emit(self, event, data=None):
        pass


async def test_action_handler_set_emits_settings_changed_event():
    bus = EventBus()
    events = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    handler = ActionHandler(
        bus=FakeBus(),
        settings_store=FakeStore(),
        credential_vault=FakeVault(),
        event_bus=bus,
    )
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "persona",
            "value": "friendly",
        },
        user_id="u1",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert len(events) == 1
    assert events[0]["key"] == "persona"
    assert events[0]["actor"] == "user:u1"
```

- [ ] **Step 3: Run the new test to verify it fails**

Run: `python -m pytest tests/sdui/test_settings_actions_facade.py -v`
Expected: FAIL with `TypeError: ActionHandler.__init__() got an unexpected keyword argument 'event_bus'`

- [ ] **Step 4: Refactor ActionHandler to own a SettingsService**

In `src/breadmind/sdui/actions.py`:

1. Add `event_bus` parameter to `ActionHandler.__init__`, construct a `SettingsService` and a `SettingsReloadRegistry` owned by this handler:

```python
    def __init__(
        self,
        bus,
        *,
        message_handler=None,
        working_memory=None,
        settings_store=None,
        credential_vault=None,
        event_bus=None,
        settings_service=None,
    ) -> None:
        self._bus = bus
        self._message_handler = message_handler
        self._working_memory = working_memory
        self._settings_store = settings_store
        self._credential_vault = credential_vault

        if settings_service is None and settings_store is not None:
            from breadmind.settings.reload_registry import SettingsReloadRegistry
            from breadmind.settings.service import SettingsService
            settings_service = SettingsService(
                store=settings_store,
                vault=credential_vault,
                audit_sink=self._record_audit,
                reload_registry=SettingsReloadRegistry(),
                event_bus=event_bus,
            )
        self._settings_service = settings_service
```

2. Change `_record_audit` signature to accept the keyword arguments the service passes and return an integer ID. The existing UI code that calls `_record_audit(kind, key, user_id, summary)` keeps its current form through a positional-or-keyword shim:

```python
    async def _record_audit(
        self,
        kind=None,
        key=None,
        actor=None,
        summary=None,
        *,
        old_preview=None,
        new_preview=None,
        # legacy positional args kept as aliases:
        user_id=None,
    ) -> int:
        # Legacy callers pass user_id; new callers pass actor.
        if actor is None and user_id is not None:
            actor = f"user:{user_id}"
        entry = {
            "kind": kind,
            "key": key,
            "actor": actor,
            "summary": summary,
            "old_preview": old_preview,
            "new_preview": new_preview,
            "ts": _now(),
        }
        self._audit.append(entry)
        if len(self._audit) > 200:
            self._audit.pop(0)
        return len(self._audit)
```

(Keep any other lines from the existing `_record_audit` — especially the `_audit` FIFO buffer and the existing exception swallowing — and wrap them around the new payload shape.)

3. Rewrite the five settings action methods as thin translators:

```python
    async def _settings_write(self, action, user_id):
        key = action.get("key")
        value = action.get("value")
        result = await self._settings_service.set(
            key, value, actor=f"user:{user_id}"
        )
        return {
            "ok": result.ok,
            "persisted": result.persisted,
            "error": result.error,
            "restart_required": result.restart_required,
            "refresh_view": "settings_view",
        }

    async def _settings_append(self, action, user_id):
        key = action.get("key")
        item = action.get("item") or action.get("value")
        # Preserve existing bootstrap exception for safety_permissions_admin_users.
        if key == "safety_permissions_admin_users":
            existing = await self._settings_store.get_setting(key) or []
            if not existing and user_id:
                # Bootstrap path: first admin may be the current user.
                pass  # Allow; handled below by regular append.
        result = await self._settings_service.append(
            key, item, actor=f"user:{user_id}"
        )
        return {
            "ok": result.ok,
            "persisted": result.persisted,
            "error": result.error,
            "refresh_view": "settings_view",
        }

    async def _settings_update_item(self, action, user_id):
        key = action.get("key")
        result = await self._settings_service.update_item(
            key,
            match_field=action.get("match_field"),
            match_value=action.get("match_value"),
            patch=action.get("patch") or action.get("value") or {},
            actor=f"user:{user_id}",
        )
        return {
            "ok": result.ok,
            "persisted": result.persisted,
            "error": result.error,
            "refresh_view": "settings_view",
        }

    async def _credential_store(self, action, user_id):
        # Form submits field values inside action["values"]; fall back to top-level for legacy callers.
        values = action.get("values") or {}
        key = action.get("key") or values.get("key")
        value = values.get("value") or action.get("value")
        description = values.get("description") or action.get("description", "")
        result = await self._settings_service.set_credential(
            key, value, actor=f"user:{user_id}", description=description,
        )
        return {
            "ok": result.ok,
            "persisted": result.persisted,
            "error": result.error,
            "refresh_view": "settings_view",
        }

    async def _credential_delete(self, action, user_id):
        key = action.get("key") or (action.get("values") or {}).get("key")
        result = await self._settings_service.delete_credential(
            key, actor=f"user:{user_id}",
        )
        return {
            "ok": result.ok,
            "persisted": result.persisted,
            "error": result.error,
            "refresh_view": "settings_view",
        }
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python -m pytest tests/sdui/test_settings_actions_facade.py -v`
Expected: 1 passed

- [ ] **Step 6: Run the full SDUI suite to confirm no regressions**

Run: `python -m pytest tests/sdui/ -v --tb=short`
Expected: 543 passed (baseline + 1 new). If any pre-existing test fails, do NOT proceed — fix the ActionHandler compatibility layer until the full suite is green.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/sdui/actions.py tests/sdui/test_settings_actions_facade.py
git commit -m "refactor(sdui): route ActionHandler settings kinds through SettingsService"
```

---

## Task 7: Eight agent tools

**Files:**
- Create: `src/breadmind/tools/settings_tools.py`
- Test: `tests/tools/test_settings_tools.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/tools/test_settings_tools.py`:

```python
import json

import pytest

from breadmind.settings.service import SetResult
from breadmind.tools.settings_tools import build_settings_tools


class StubService:
    def __init__(self):
        self.calls = []

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))

    async def get(self, key):
        self._record("get", key=key)
        return {"default_provider": "claude"}

    async def set(self, key, value, *, actor):
        self._record("set", key=key, value=value, actor=actor)
        return SetResult(ok=True, operation="set", key=key, persisted=True, hot_reloaded=True, audit_id=1)

    async def append(self, key, item, *, actor):
        self._record("append", key=key, item=item, actor=actor)
        return SetResult(ok=True, operation="append", key=key, persisted=True, hot_reloaded=True, audit_id=2)

    async def update_item(self, key, *, match_field, match_value, patch, actor):
        self._record("update_item", key=key, match_field=match_field,
                     match_value=match_value, patch=patch, actor=actor)
        return SetResult(ok=True, operation="update_item", key=key, persisted=True, hot_reloaded=True, audit_id=3)

    async def delete_item(self, key, *, match_field, match_value, actor):
        self._record("delete_item", key=key, match_field=match_field,
                     match_value=match_value, actor=actor)
        return SetResult(ok=True, operation="delete_item", key=key, persisted=True, hot_reloaded=True, audit_id=4)

    async def set_credential(self, key, value, *, actor, description=""):
        self._record("set_credential", key=key, value=value,
                     actor=actor, description=description)
        return SetResult(ok=True, operation="credential_store", key=key, persisted=True, hot_reloaded=True, audit_id=5)

    async def delete_credential(self, key, *, actor):
        self._record("delete_credential", key=key, actor=actor)
        return SetResult(ok=True, operation="credential_delete", key=key, persisted=True, hot_reloaded=True, audit_id=6)


@pytest.fixture
def tools():
    svc = StubService()
    return svc, build_settings_tools(service=svc, actor="agent:core")


async def test_get_setting_returns_json_string(tools):
    svc, t = tools
    result = await t["breadmind_get_setting"](key="llm")
    parsed = json.loads(result)
    assert parsed["key"] == "llm"
    assert parsed["value"] == {"default_provider": "claude"}


async def test_set_setting_parses_json_value(tools):
    svc, t = tools
    result = await t["breadmind_set_setting"](
        key="persona", value='"friendly"'
    )
    assert result.startswith("OK")
    assert svc.calls[-1] == ("set", {"key": "persona", "value": "friendly", "actor": "agent:core"})


async def test_set_setting_accepts_complex_json(tools):
    svc, t = tools
    payload = '{"default_provider":"gemini","default_model":"gemini-2.0-flash"}'
    result = await t["breadmind_set_setting"](key="llm", value=payload)
    assert result.startswith("OK")
    assert svc.calls[-1][1]["value"] == {
        "default_provider": "gemini",
        "default_model": "gemini-2.0-flash",
    }


async def test_set_setting_invalid_json_returns_error(tools):
    svc, t = tools
    result = await t["breadmind_set_setting"](key="persona", value="not-json")
    assert result.startswith("ERROR")
    assert "json" in result.lower()
    assert svc.calls == []


async def test_append_setting_parses_item_json(tools):
    svc, t = tools
    item_json = '{"name":"github","command":"npx","args":["-y","gh"],"env":{},"enabled":true}'
    result = await t["breadmind_append_setting"](key="mcp_servers", item=item_json)
    assert result.startswith("OK")
    assert svc.calls[-1][1]["item"]["name"] == "github"


async def test_update_setting_item(tools):
    svc, t = tools
    result = await t["breadmind_update_setting_item"](
        key="mcp_servers",
        match_field="name",
        match_value="github",
        patch='{"enabled":false}',
    )
    assert result.startswith("OK")
    call = svc.calls[-1][1]
    assert call["patch"] == {"enabled": False}


async def test_delete_setting_item(tools):
    svc, t = tools
    result = await t["breadmind_delete_setting_item"](
        key="mcp_servers", match_field="name", match_value="github"
    )
    assert result.startswith("OK")


async def test_set_credential_passes_through(tools):
    svc, t = tools
    result = await t["breadmind_set_credential"](
        key="apikey:anthropic", value="sk-ant-xxx", description="primary"
    )
    assert result.startswith("OK")
    assert svc.calls[-1][1]["value"] == "sk-ant-xxx"
    assert svc.calls[-1][1]["description"] == "primary"


async def test_delete_credential(tools):
    svc, t = tools
    result = await t["breadmind_delete_credential"](key="apikey:anthropic")
    assert result.startswith("OK")


async def test_list_settings_uses_catalogue(tools):
    svc, t = tools
    result = await t["breadmind_list_settings"](query="llm")
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert any(entry["key"] == "llm" for entry in parsed)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_settings_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'breadmind.tools.settings_tools'`

- [ ] **Step 3: Implement the tool module**

Create `src/breadmind/tools/settings_tools.py`:

```python
"""Built-in agent tools for reading and modifying BreadMind runtime settings.

Each tool is a thin wrapper around :class:`breadmind.settings.service.SettingsService`.
Values that may be scalars, lists, or dicts travel as JSON strings so a single
``str``-typed parameter is enough for the LLM to express any shape.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from breadmind.settings.service import SetResult
from breadmind.tools.registry import tool


def _parse_json(raw: str, field: str) -> tuple[Any, str | None]:
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"ERROR: invalid JSON for {field} — {exc.msg}"


def _format(result: SetResult) -> str:
    return result.summary()


def build_settings_tools(
    *,
    service: Any,
    actor: str = "agent:core",
) -> dict[str, Callable[..., Any]]:
    """Create tool callables bound to the given service and actor.

    Returns a name→callable map. The caller is expected to register each entry
    with a :class:`breadmind.tools.registry.ToolRegistry`.
    """

    @tool(
        description=(
            "Read a BreadMind runtime setting. Returns a JSON string with the "
            "key and its current value. Credential keys (apikey:*, vault:*) "
            "always return '●●●●'."
        ),
        read_only=True,
        concurrency_safe=True,
    )
    async def breadmind_get_setting(key: str) -> str:
        value = await service.get(key)
        return json.dumps({"key": key, "value": value}, ensure_ascii=False)

    @tool(
        description=(
            "Search the settings catalogue. Returns matching entries as JSON: "
            "[{label, key, tab, field_id}, ...]. Use to discover the correct "
            "settings key before calling set/append."
        ),
        read_only=True,
        concurrency_safe=True,
    )
    async def breadmind_list_settings(query: str = "", tab: str = "") -> str:
        from breadmind.sdui.settings_index import search_settings
        entries = search_settings(query or "")
        if tab:
            entries = [e for e in entries if e.get("tab") == tab]
        return json.dumps(entries, ensure_ascii=False)

    @tool(
        description=(
            "Overwrite a BreadMind runtime setting. `value` is a JSON-encoded "
            "string: '\"friendly\"', '{\"default_provider\":\"gemini\"}', "
            "'[1,2,3]', etc. Triggers hot reload when the setting's owner "
            "subscribes. Returns 'OK ...' on success or 'ERROR: ...' otherwise."
        ),
    )
    async def breadmind_set_setting(key: str, value: str) -> str:
        parsed, err = _parse_json(value, "value")
        if err:
            return err
        result = await service.set(key, parsed, actor=actor)
        return _format(result)

    @tool(
        description=(
            "Append an item to a list-valued setting (e.g. mcp_servers, "
            "skill_markets, safety_blacklist). `item` is a JSON object or "
            "scalar. Returns 'OK ...' or 'ERROR: ...'."
        ),
    )
    async def breadmind_append_setting(key: str, item: str) -> str:
        parsed, err = _parse_json(item, "item")
        if err:
            return err
        result = await service.append(key, parsed, actor=actor)
        return _format(result)

    @tool(
        description=(
            "Update a single item inside a list-valued setting by matching "
            "one field. `patch` is a JSON object merged into the matched item. "
            "Example: update_setting_item('mcp_servers', 'name', 'github', "
            "'{\"enabled\":false}')."
        ),
    )
    async def breadmind_update_setting_item(
        key: str, match_field: str, match_value: str, patch: str
    ) -> str:
        parsed_patch, err = _parse_json(patch, "patch")
        if err:
            return err
        result = await service.update_item(
            key,
            match_field=match_field,
            match_value=match_value,
            patch=parsed_patch,
            actor=actor,
        )
        return _format(result)

    @tool(
        description=(
            "Delete a single item from a list-valued setting by matching one "
            "field. Example: delete_setting_item('mcp_servers','name','github')."
        ),
    )
    async def breadmind_delete_setting_item(
        key: str, match_field: str, match_value: str
    ) -> str:
        result = await service.delete_item(
            key,
            match_field=match_field,
            match_value=match_value,
            actor=actor,
        )
        return _format(result)

    @tool(
        description=(
            "Store a secret credential (apikey:anthropic, vault:ssh:host, …). "
            "Plaintext is written to the encrypted CredentialVault and never "
            "logged. Writes that target sensitive keys may require user "
            "approval — in that case the return starts with 'PENDING:'."
        ),
    )
    async def breadmind_set_credential(
        key: str, value: str, description: str = ""
    ) -> str:
        result = await service.set_credential(
            key, value, actor=actor, description=description
        )
        return _format(result)

    @tool(
        description="Delete a stored credential by its full key.",
    )
    async def breadmind_delete_credential(key: str) -> str:
        result = await service.delete_credential(key, actor=actor)
        return _format(result)

    return {
        "breadmind_get_setting": breadmind_get_setting,
        "breadmind_list_settings": breadmind_list_settings,
        "breadmind_set_setting": breadmind_set_setting,
        "breadmind_append_setting": breadmind_append_setting,
        "breadmind_update_setting_item": breadmind_update_setting_item,
        "breadmind_delete_setting_item": breadmind_delete_setting_item,
        "breadmind_set_credential": breadmind_set_credential,
        "breadmind_delete_credential": breadmind_delete_credential,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_settings_tools.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/settings_tools.py tests/tools/test_settings_tools.py
git commit -m "feat(tools): add 8 breadmind_*_setting agent tools"
```

---

## Task 8: Tool registration + web app wiring

**Files:**
- Create: `src/breadmind/tools/settings_tool_registration.py`
- Modify: `src/breadmind/web/routes/ui.py`

- [ ] **Step 1: Write an end-to-end wiring test**

Create `tests/tools/test_settings_tools_e2e.py`:

```python
from breadmind.core.events import EventBus
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService
from breadmind.tools.registry import ToolRegistry
from breadmind.tools.settings_tool_registration import register_settings_tools


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
    async def store(self, cred_id, value, metadata=None):
        return cred_id
    async def delete(self, cred_id):
        return True


async def _noop_audit(**kwargs):
    return 1


async def test_register_settings_tools_adds_eight_entries():
    registry = ToolRegistry()
    service = SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=EventBus(),
    )
    register_settings_tools(registry, service=service, actor="agent:core")

    names = set(registry.list_tools())
    assert {
        "breadmind_get_setting",
        "breadmind_list_settings",
        "breadmind_set_setting",
        "breadmind_append_setting",
        "breadmind_update_setting_item",
        "breadmind_delete_setting_item",
        "breadmind_set_credential",
        "breadmind_delete_credential",
    }.issubset(names)


async def test_registered_set_setting_actually_persists():
    registry = ToolRegistry()
    store = FakeStore()
    store.data["persona"] = "professional"
    service = SettingsService(
        store=store,
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=EventBus(),
    )
    register_settings_tools(registry, service=service, actor="agent:core")

    tool_fn = registry.get_tool_fn("breadmind_set_setting")
    assert tool_fn is not None
    result = await tool_fn(key="persona", value='"friendly"')
    assert result.startswith("OK")
    assert store.data["persona"] == "friendly"
```

(Note: if `ToolRegistry` exposes `list_tools`/`get_tool_fn` under different names, the corresponding method names from `src/breadmind/tools/registry.py` should be used instead — do not add new methods to the registry for this test. Check `registry.py` and use the existing accessors.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/tools/test_settings_tools_e2e.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'breadmind.tools.settings_tool_registration'`

- [ ] **Step 3: Implement registration entry point**

Create `src/breadmind/tools/settings_tool_registration.py`:

```python
"""Register ``breadmind_*_setting`` tools into a ``ToolRegistry``."""
from __future__ import annotations

from typing import Any

from breadmind.tools.settings_tools import build_settings_tools


def register_settings_tools(
    registry: Any,
    *,
    service: Any,
    actor: str = "agent:core",
) -> list[str]:
    """Bind the eight built-in settings tools to ``registry``.

    Returns the list of tool names that were registered (in insertion order).
    """
    tools = build_settings_tools(service=service, actor=actor)
    for fn in tools.values():
        registry.register(fn)
    return list(tools.keys())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/tools/test_settings_tools_e2e.py -v`
Expected: 2 passed

- [ ] **Step 5: Wire SettingsService and tools into the web app**

In `src/breadmind/web/routes/ui.py` inside `_ensure_projector`, after `app.state.uispec_projector = projector` but before `app.state.sdui_action_handler = ActionHandler(...)`:

```python
        from breadmind.settings.reload_registry import SettingsReloadRegistry
        from breadmind.settings.service import SettingsService

        reload_registry = SettingsReloadRegistry()
        settings_service = SettingsService(
            store=settings_store,
            vault=credential_vault,
            audit_sink=None,  # filled in after ActionHandler below
            reload_registry=reload_registry,
            event_bus=flow_bus,
        )
        app.state.settings_reload_registry = reload_registry
        app.state.settings_service = settings_service
```

Update the `ActionHandler` construction to pass the shared service and then back-fill the audit sink so both the UI and agent paths share one audit buffer:

```python
        action_handler = ActionHandler(
            bus=flow_bus,
            message_handler=message_handler,
            working_memory=working_memory,
            settings_store=settings_store,
            credential_vault=credential_vault,
            event_bus=flow_bus,
            settings_service=settings_service,
        )
        settings_service._audit_sink = action_handler._record_audit
        app.state.sdui_action_handler = action_handler

        # Register built-in agent settings tools onto the tool registry used
        # by CoreAgent. The registry is typically discovered via app_state.
        tool_registry = getattr(app_state, "_tool_registry", None)
        if tool_registry is not None:
            from breadmind.tools.settings_tool_registration import (
                register_settings_tools,
            )
            register_settings_tools(
                tool_registry, service=settings_service, actor="agent:core"
            )
```

If `app_state._tool_registry` uses a different attribute name, use the same name that other tool-bootstrapping code in this repo uses (grep for `register_builtin_tools` and copy the pattern).

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `python -m pytest tests/ -v --tb=short -x`
Expected: all tests pass. If any tests that construct `ActionHandler` without `event_bus` fail, add a default `event_bus=None` branch in `ActionHandler.__init__` (the service is still constructed, just without event emission).

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/tools/settings_tool_registration.py tests/tools/test_settings_tools_e2e.py src/breadmind/web/routes/ui.py
git commit -m "feat(web): wire SettingsService + agent settings tools into web app"
```

---

## Task 9: LLMProviderHolder + reloader for `llm` and `apikey:*`

**Files:**
- Create: `src/breadmind/settings/llm_holder.py`
- Test: `tests/settings/test_llm_holder.py`, `tests/settings/test_llm_reloader.py`
- Modify: `src/breadmind/core/agent.py`, `src/breadmind/web/routes/ui.py`

- [ ] **Step 1: Write failing holder test**

Create `tests/settings/test_llm_holder.py`:

```python
from breadmind.settings.llm_holder import LLMProviderHolder


class FakeProvider:
    def __init__(self, name):
        self.name = name

    async def complete(self, prompt):
        return f"{self.name}:{prompt}"


async def test_holder_delegates_attribute_access():
    h = LLMProviderHolder(FakeProvider("A"))
    assert h.name == "A"
    assert await h.complete("hi") == "A:hi"


async def test_holder_swap_changes_delegate():
    h = LLMProviderHolder(FakeProvider("A"))
    h.swap(FakeProvider("B"))
    assert h.name == "B"
    assert await h.complete("hi") == "B:hi"


async def test_holder_rejects_none_swap():
    h = LLMProviderHolder(FakeProvider("A"))
    import pytest
    with pytest.raises(ValueError):
        h.swap(None)
    assert h.name == "A"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/settings/test_llm_holder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the holder**

Create `src/breadmind/settings/llm_holder.py`:

```python
"""Transparent proxy that lets callers keep a stable reference to an LLM
provider while the underlying instance is swapped out on hot reload."""
from __future__ import annotations

from typing import Any


class LLMProviderHolder:
    """Proxy around a live :class:`LLMProvider` instance.

    Callers can hold the holder and call ``holder.complete(...)`` as if it
    were the provider itself. ``swap(new_provider)`` atomically replaces the
    inner reference — subsequent calls go to the new provider.
    """

    def __init__(self, provider: Any) -> None:
        if provider is None:
            raise ValueError("provider must not be None")
        object.__setattr__(self, "_inner", provider)

    def swap(self, new_provider: Any) -> None:
        if new_provider is None:
            raise ValueError("new_provider must not be None")
        object.__setattr__(self, "_inner", new_provider)

    @property
    def current(self) -> Any:
        return object.__getattribute__(self, "_inner")

    def __getattr__(self, item: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), item)
```

- [ ] **Step 4: Verify holder test passes**

Run: `python -m pytest tests/settings/test_llm_holder.py -v`
Expected: 3 passed

- [ ] **Step 5: Write failing reloader integration test**

Create `tests/settings/test_llm_reloader.py`:

```python
from breadmind.settings.llm_holder import LLMProviderHolder
from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeProvider:
    def __init__(self, name):
        self.name = name


def fake_factory(config):
    return FakeProvider(config["default_provider"])


async def test_llm_key_change_swaps_provider_in_holder():
    holder = LLMProviderHolder(FakeProvider("claude"))
    registry = SettingsReloadRegistry()

    async def reload_llm(ctx):
        holder.swap(fake_factory(ctx["new"]))

    registry.register("llm", reload_llm)

    await registry.dispatch(
        key="llm",
        operation="set",
        old={"default_provider": "claude"},
        new={"default_provider": "gemini"},
    )
    assert holder.name == "gemini"


async def test_apikey_change_also_reloads_provider():
    holder = LLMProviderHolder(FakeProvider("claude-old"))
    registry = SettingsReloadRegistry()
    calls = []

    async def reload_llm(ctx):
        calls.append(ctx["key"])
        holder.swap(FakeProvider("claude-new"))

    registry.register("apikey:*", reload_llm)
    await registry.dispatch(
        key="apikey:anthropic", operation="credential_store", old=None, new=None
    )
    assert calls == ["apikey:anthropic"]
    assert holder.name == "claude-new"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/settings/test_llm_reloader.py -v`
Expected: 2 passed (pure plumbing, no new code needed — holder + registry already exist)

- [ ] **Step 7: Wire holder into CoreAgent and web app**

In `src/breadmind/core/agent.py`:
- Change `self._provider = provider` to accept either a raw provider or an `LLMProviderHolder`:

```python
        from breadmind.settings.llm_holder import LLMProviderHolder
        if not isinstance(provider, LLMProviderHolder):
            provider = LLMProviderHolder(provider)
        self._provider = provider
```

CoreAgent code that does `self._provider.chat(...)`/`self._provider.complete(...)` continues to work because the holder proxies attributes through `__getattr__`.

In `src/breadmind/web/routes/ui.py`, during `_ensure_projector`, after constructing `settings_service`:

```python
        llm_holder = None
        try:
            existing_provider = getattr(app_state, "_llm_provider", None)
            if existing_provider is not None:
                from breadmind.settings.llm_holder import LLMProviderHolder
                llm_holder = LLMProviderHolder(existing_provider)
                app_state._llm_provider = llm_holder

                async def _reload_llm(ctx):
                    from breadmind.llm.factory import create_provider
                    new_provider = create_provider(getattr(app_state, "_config", None))
                    llm_holder.swap(new_provider)

                reload_registry.register("llm", _reload_llm)
                reload_registry.register("apikey:*", _reload_llm)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "LLM hot-reload wiring skipped: %s", exc
            )
```

- [ ] **Step 8: Run the full test suite**

Run: `python -m pytest tests/ -v -x --tb=short`
Expected: all tests pass. If the CoreAgent constructor change breaks existing tests, update those tests to use `LLMProviderHolder(fake_provider)` or rely on the auto-wrap path.

- [ ] **Step 9: Commit**

```bash
git add src/breadmind/settings/llm_holder.py tests/settings/test_llm_holder.py tests/settings/test_llm_reloader.py src/breadmind/core/agent.py src/breadmind/web/routes/ui.py
git commit -m "feat(settings): hot-reload LLM provider via holder proxy"
```

---

## Task 10: Persona / prompt component reloader

**Files:**
- Modify: `src/breadmind/core/agent.py`
- Modify: `src/breadmind/web/routes/ui.py`
- Test: `tests/settings/test_persona_reloader.py`

- [ ] **Step 1: Write failing test**

Create `tests/settings/test_persona_reloader.py`:

```python
from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeAgent:
    def __init__(self):
        self.persona = "professional"
        self.custom_prompts: dict = {}
        self.custom_instructions = ""
        self.reload_calls = 0

    def reload_prompt_components(self, *, persona=None, custom_prompts=None, custom_instructions=None):
        if persona is not None:
            self.persona = persona
        if custom_prompts is not None:
            self.custom_prompts = custom_prompts
        if custom_instructions is not None:
            self.custom_instructions = custom_instructions
        self.reload_calls += 1


async def test_persona_change_triggers_agent_reload():
    agent = FakeAgent()
    registry = SettingsReloadRegistry()

    async def reload_persona(ctx):
        agent.reload_prompt_components(persona=ctx["new"])

    async def reload_custom_prompts(ctx):
        agent.reload_prompt_components(custom_prompts=ctx["new"])

    async def reload_custom_instructions(ctx):
        agent.reload_prompt_components(custom_instructions=ctx["new"])

    registry.register("persona", reload_persona)
    registry.register("custom_prompts", reload_custom_prompts)
    registry.register("custom_instructions", reload_custom_instructions)

    await registry.dispatch(key="persona", operation="set", old="professional", new="friendly")
    await registry.dispatch(key="custom_prompts", operation="set", old={}, new={"greet": "hi"})
    await registry.dispatch(key="custom_instructions", operation="set", old="", new="be brief")

    assert agent.persona == "friendly"
    assert agent.custom_prompts == {"greet": "hi"}
    assert agent.custom_instructions == "be brief"
    assert agent.reload_calls == 3
```

- [ ] **Step 2: Run test to verify it passes (pure plumbing)**

Run: `python -m pytest tests/settings/test_persona_reloader.py -v`
Expected: 1 passed

- [ ] **Step 3: Add `reload_prompt_components` to CoreAgent**

In `src/breadmind/core/agent.py`, add this method to `CoreAgent`:

```python
    def reload_prompt_components(
        self,
        *,
        persona: str | None = None,
        custom_prompts: dict | None = None,
        custom_instructions: str | None = None,
    ) -> None:
        """Rebuild the cached system prompt when prompt-related settings change.

        Any argument left as ``None`` is kept at its current value. Called by
        the settings reload registry when ``persona``, ``custom_prompts``, or
        ``custom_instructions`` is written.
        """
        if persona is not None:
            self.set_persona(persona)
        if custom_prompts is not None:
            self._custom_prompts = custom_prompts
            self._rebuild_system_prompt()
        if custom_instructions is not None:
            self._custom_instructions = custom_instructions
            self._rebuild_system_prompt()
```

If `_rebuild_system_prompt` does not yet exist on CoreAgent, implement it as a thin wrapper that re-invokes the existing `PromptBuilder.build(...)` call path with the current persona/prompt state and stores the result in `self._system_prompt`. Use `set_persona`'s existing body (at roughly `src/breadmind/core/agent.py:114-122`) as the template.

- [ ] **Step 4: Wire subscribers in the web app**

In `src/breadmind/web/routes/ui.py` after the LLM wiring block, add:

```python
        core_agent = getattr(app_state, "_agent", None)
        if core_agent is not None:
            async def _reload_persona(ctx):
                core_agent.reload_prompt_components(persona=ctx["new"])

            async def _reload_custom_prompts(ctx):
                core_agent.reload_prompt_components(custom_prompts=ctx["new"])

            async def _reload_custom_instructions(ctx):
                core_agent.reload_prompt_components(custom_instructions=ctx["new"])

            reload_registry.register("persona", _reload_persona)
            reload_registry.register("custom_prompts", _reload_custom_prompts)
            reload_registry.register("custom_instructions", _reload_custom_instructions)
```

Use whichever attribute actually holds the running `CoreAgent` instance (`_agent`, `_core_agent`, etc. — grep the file for `CoreAgent(`).

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -v -x --tb=short`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/agent.py src/breadmind/web/routes/ui.py tests/settings/test_persona_reloader.py
git commit -m "feat(settings): hot-reload persona, custom_prompts, custom_instructions"
```

---

## Task 11: SafetyGuard reloader

**Files:**
- Modify: `src/breadmind/core/safety_guard.py`
- Modify: `src/breadmind/web/routes/ui.py`
- Test: `tests/settings/test_safety_reloader.py`

- [ ] **Step 1: Write failing test**

Create `tests/settings/test_safety_reloader.py`:

```python
from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeGuard:
    def __init__(self):
        self.blacklist = []
        self.approval = {}
        self.permissions = {}
        self.tool_security = {}

    def reload(self, **kwargs):
        for k, v in kwargs.items():
            if v is not None:
                setattr(self, k, v)


async def test_safety_keys_reload_guard():
    guard = FakeGuard()
    registry = SettingsReloadRegistry()

    async def reload_bl(ctx):
        guard.reload(blacklist=ctx["new"])

    async def reload_appr(ctx):
        guard.reload(approval=ctx["new"])

    async def reload_perm(ctx):
        guard.reload(permissions=ctx["new"])

    async def reload_tool(ctx):
        guard.reload(tool_security=ctx["new"])

    registry.register("safety_blacklist", reload_bl)
    registry.register("safety_approval", reload_appr)
    registry.register("safety_permissions", reload_perm)
    registry.register("tool_security", reload_tool)

    await registry.dispatch(key="safety_blacklist", operation="set", old=[], new=["rm -rf /"])
    await registry.dispatch(key="safety_approval", operation="set", old={}, new={"cmd": True})
    await registry.dispatch(key="safety_permissions", operation="set", old={}, new={"shell": "admin"})
    await registry.dispatch(key="tool_security", operation="set", old={}, new={"command_whitelist_enabled": True})

    assert guard.blacklist == ["rm -rf /"]
    assert guard.approval == {"cmd": True}
    assert guard.permissions == {"shell": "admin"}
    assert guard.tool_security == {"command_whitelist_enabled": True}
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/settings/test_safety_reloader.py -v`
Expected: 1 passed

- [ ] **Step 3: Add `reload` method to SafetyGuard**

In `src/breadmind/core/safety_guard.py`, add a method:

```python
    def reload(
        self,
        *,
        blacklist: Any = None,
        approval: Any = None,
        permissions: Any = None,
        tool_security: Any = None,
    ) -> None:
        """Replace live rule sets from new settings. ``None`` means keep current."""
        if blacklist is not None:
            self._blacklist = list(blacklist)
        if approval is not None:
            self._approval_rules = dict(approval)
        if permissions is not None:
            self._permissions = dict(permissions)
        if tool_security is not None:
            self._tool_security = dict(tool_security)
```

Use the existing attribute names already present on SafetyGuard (grep for `self._blacklist`, `self._approval_rules`, `self._permissions`, `self._tool_security` in `src/breadmind/core/safety_guard.py`). If any are absent, rename the reload keyword to match what is actually there — do not invent new fields.

- [ ] **Step 4: Wire subscribers in the web app**

In `src/breadmind/web/routes/ui.py` after the persona wiring block:

```python
        safety_guard = getattr(app_state, "_safety_guard", None)
        if safety_guard is not None:
            async def _reload_blacklist(ctx):
                safety_guard.reload(blacklist=ctx["new"])

            async def _reload_approval(ctx):
                safety_guard.reload(approval=ctx["new"])

            async def _reload_permissions(ctx):
                safety_guard.reload(permissions=ctx["new"])

            async def _reload_tool_security(ctx):
                safety_guard.reload(tool_security=ctx["new"])

            reload_registry.register("safety_blacklist", _reload_blacklist)
            reload_registry.register("safety_approval", _reload_approval)
            reload_registry.register("safety_permissions", _reload_permissions)
            reload_registry.register("safety_permissions_admin_users", _reload_permissions)
            reload_registry.register("tool_security", _reload_tool_security)
```

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -v -x --tb=short`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/safety_guard.py src/breadmind/web/routes/ui.py tests/settings/test_safety_reloader.py
git commit -m "feat(settings): hot-reload SafetyGuard rules"
```

---

## Task 12: Runtime config reloader (timeouts, retry, limits, polling, logging, memory_gc, agent_timeouts)

**Files:**
- Create: `src/breadmind/settings/runtime_config.py`
- Test: `tests/settings/test_runtime_reloader.py`
- Modify: `src/breadmind/web/routes/ui.py`

- [ ] **Step 1: Write failing test**

Create `tests/settings/test_runtime_reloader.py`:

```python
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.runtime_config import RuntimeConfigHolder


async def test_runtime_holder_updates_on_each_key():
    holder = RuntimeConfigHolder(initial={
        "retry_config": {"max_attempts": 3},
        "limits_config": {"max_turns": 10},
        "polling_config": {"interval_seconds": 5},
        "agent_timeouts": {"tool_seconds": 30},
        "system_timeouts": {"chat_seconds": 120},
        "logging_config": {"level": "INFO"},
        "memory_gc_config": {"interval_minutes": 60},
    })
    registry = SettingsReloadRegistry()
    holder.register(registry)

    await registry.dispatch(
        key="retry_config", operation="set",
        old={"max_attempts": 3}, new={"max_attempts": 5},
    )
    assert holder.get("retry_config") == {"max_attempts": 5}

    await registry.dispatch(
        key="limits_config", operation="set",
        old={"max_turns": 10}, new={"max_turns": 20},
    )
    assert holder.get("limits_config") == {"max_turns": 20}

    await registry.dispatch(
        key="logging_config", operation="set",
        old={"level": "INFO"}, new={"level": "DEBUG"},
    )
    assert holder.get("logging_config") == {"level": "DEBUG"}


async def test_runtime_holder_logging_config_updates_root_logger():
    import logging

    holder = RuntimeConfigHolder(initial={"logging_config": {"level": "INFO"}})
    registry = SettingsReloadRegistry()
    holder.register(registry)

    await registry.dispatch(
        key="logging_config", operation="set",
        old={"level": "INFO"}, new={"level": "WARNING"},
    )
    assert logging.getLogger().level == logging.WARNING
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/settings/test_runtime_reloader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'breadmind.settings.runtime_config'`

- [ ] **Step 3: Implement RuntimeConfigHolder**

Create `src/breadmind/settings/runtime_config.py`:

```python
"""Holds the live copy of runtime configuration keys that CoreAgent and its
collaborators read through indirection so hot reload is transparent."""
from __future__ import annotations

import logging
from typing import Any

from breadmind.settings.reload_registry import SettingsReloadRegistry

_KEYS = (
    "retry_config",
    "limits_config",
    "polling_config",
    "agent_timeouts",
    "system_timeouts",
    "logging_config",
    "memory_gc_config",
)


class RuntimeConfigHolder:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._state: dict[str, Any] = dict(initial or {})

    def get(self, key: str) -> Any:
        return self._state.get(key)

    def register(self, registry: SettingsReloadRegistry) -> None:
        for key in _KEYS:
            registry.register(key, self._make_reloader(key))

    def _make_reloader(self, key: str):
        async def _reload(ctx: dict[str, Any]) -> None:
            self._state[key] = ctx["new"]
            if key == "logging_config":
                self._apply_logging(ctx["new"] or {})
        return _reload

    @staticmethod
    def _apply_logging(cfg: dict[str, Any]) -> None:
        level_name = str(cfg.get("level", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)
        logging.getLogger().setLevel(level)
```

- [ ] **Step 4: Run test**

Run: `python -m pytest tests/settings/test_runtime_reloader.py -v`
Expected: 2 passed

- [ ] **Step 5: Wire the holder into the web app**

In `src/breadmind/web/routes/ui.py` after the SafetyGuard wiring:

```python
        from breadmind.settings.runtime_config import RuntimeConfigHolder
        initial_runtime: dict = {}
        for key in (
            "retry_config", "limits_config", "polling_config",
            "agent_timeouts", "system_timeouts", "logging_config",
            "memory_gc_config",
        ):
            val = await settings_store.get_setting(key)
            if val is not None:
                initial_runtime[key] = val
        runtime_holder = RuntimeConfigHolder(initial=initial_runtime)
        runtime_holder.register(reload_registry)
        app.state.runtime_config_holder = runtime_holder
```

- [ ] **Step 6: Run full suite**

Run: `python -m pytest tests/ -v -x --tb=short`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/settings/runtime_config.py tests/settings/test_runtime_reloader.py src/breadmind/web/routes/ui.py
git commit -m "feat(settings): hot-reload runtime config keys via RuntimeConfigHolder"
```

---

## Task 13: MCP + plugin + monitoring reloaders

**Files:**
- Modify: `src/breadmind/web/routes/ui.py`
- Test: `tests/settings/test_mcp_reloader.py`

- [ ] **Step 1: Write failing test**

Create `tests/settings/test_mcp_reloader.py`:

```python
from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeMcpManager:
    def __init__(self):
        self.apply_calls = []

    async def apply_config(self, mcp_cfg=None, servers=None):
        self.apply_calls.append((mcp_cfg, servers))


class FakePluginManager:
    def __init__(self):
        self.market_calls = []

    async def apply_markets(self, markets):
        self.market_calls.append(markets)


class FakeMonitoring:
    def __init__(self):
        self.calls = []

    async def apply(self, *, monitoring_config=None, loop_protector=None,
                    scheduler_cron=None, webhook_endpoints=None):
        self.calls.append((monitoring_config, loop_protector, scheduler_cron, webhook_endpoints))


async def test_mcp_keys_trigger_manager_apply_config():
    mgr = FakeMcpManager()
    registry = SettingsReloadRegistry()

    async def reload_mcp_global(ctx):
        await mgr.apply_config(mcp_cfg=ctx["new"])

    async def reload_mcp_servers(ctx):
        await mgr.apply_config(servers=ctx["new"])

    registry.register("mcp", reload_mcp_global)
    registry.register("mcp_servers", reload_mcp_servers)

    await registry.dispatch(key="mcp", operation="set", old={}, new={"auto_discover": True})
    await registry.dispatch(key="mcp_servers", operation="set", old=[], new=[{"name": "x"}])
    assert mgr.apply_calls == [({"auto_discover": True}, None), (None, [{"name": "x"}])]


async def test_skill_markets_triggers_plugin_manager():
    plugins = FakePluginManager()
    registry = SettingsReloadRegistry()

    async def reload_markets(ctx):
        await plugins.apply_markets(ctx["new"])

    registry.register("skill_markets", reload_markets)
    await registry.dispatch(key="skill_markets", operation="set", old=[], new=[{"url": "x"}])
    assert plugins.market_calls == [[{"url": "x"}]]


async def test_monitoring_keys_trigger_monitoring_apply():
    mon = FakeMonitoring()
    registry = SettingsReloadRegistry()

    async def reload_monitoring(ctx):
        await mon.apply(monitoring_config=ctx["new"])

    async def reload_loop(ctx):
        await mon.apply(loop_protector=ctx["new"])

    async def reload_scheduler(ctx):
        await mon.apply(scheduler_cron=ctx["new"])

    async def reload_webhooks(ctx):
        await mon.apply(webhook_endpoints=ctx["new"])

    registry.register("monitoring_config", reload_monitoring)
    registry.register("loop_protector", reload_loop)
    registry.register("scheduler_cron", reload_scheduler)
    registry.register("webhook_endpoints", reload_webhooks)

    await registry.dispatch(key="monitoring_config", operation="set", old={}, new={"enabled": True})
    await registry.dispatch(key="loop_protector", operation="set", old={}, new={"cooldown_minutes": 5})
    await registry.dispatch(key="scheduler_cron", operation="set", old={}, new={"enabled": False})
    await registry.dispatch(key="webhook_endpoints", operation="set", old=[], new=[{"url": "x"}])

    assert len(mon.calls) == 4
```

- [ ] **Step 2: Run test to verify it passes (pure plumbing)**

Run: `python -m pytest tests/settings/test_mcp_reloader.py -v`
Expected: 3 passed

- [ ] **Step 3: Wire real MCP/plugin/monitoring subscribers**

In `src/breadmind/web/routes/ui.py` after the RuntimeConfigHolder wiring, add the subscriber blocks. Each block guards against the target manager being absent so the wiring never crashes for deployments that do not run that subsystem:

```python
        from breadmind.mcp.server_manager import ServerManager  # noqa: F401 -- for type hints
        mcp_manager_obj = getattr(app_state, "_mcp_manager", None)
        if mcp_manager_obj is not None:
            async def _reload_mcp_global(ctx):
                try:
                    await mcp_manager_obj.apply_config(mcp_cfg=ctx["new"])
                except AttributeError:
                    # Fall back to event-based API if apply_config is absent.
                    await flow_bus.async_emit("mcp_server_reload", {"config": ctx["new"]})

            async def _reload_mcp_servers(ctx):
                try:
                    await mcp_manager_obj.apply_config(servers=ctx["new"])
                except AttributeError:
                    await flow_bus.async_emit("mcp_server_reload", {"servers": ctx["new"]})

            reload_registry.register("mcp", _reload_mcp_global)
            reload_registry.register("mcp_servers", _reload_mcp_servers)

        plugin_manager_obj = getattr(app_state, "_plugin_mgr", None)
        if plugin_manager_obj is not None:
            async def _reload_skill_markets(ctx):
                apply = getattr(plugin_manager_obj, "apply_markets", None)
                if apply is not None:
                    await apply(ctx["new"])

            reload_registry.register("skill_markets", _reload_skill_markets)

        monitoring_obj = getattr(app_state, "_monitoring_manager", None)
        if monitoring_obj is not None:
            def _monitoring_setter(kw):
                async def _fn(ctx):
                    apply = getattr(monitoring_obj, "apply", None)
                    if apply is not None:
                        await apply(**{kw: ctx["new"]})
                return _fn

            reload_registry.register("monitoring_config", _monitoring_setter("monitoring_config"))
            reload_registry.register("loop_protector", _monitoring_setter("loop_protector"))
            reload_registry.register("scheduler_cron", _monitoring_setter("scheduler_cron"))
            reload_registry.register("webhook_endpoints", _monitoring_setter("webhook_endpoints"))
```

If `apply_config` / `apply_markets` / `apply` do not yet exist on the target managers, **do not invent them in this task** — the fallback `try/except AttributeError` path already handles absence by emitting the existing event names. A follow-up task can add the direct methods if we see reload misses in production.

- [ ] **Step 4: Run full suite**

Run: `python -m pytest tests/ -v -x --tb=short`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add tests/settings/test_mcp_reloader.py src/breadmind/web/routes/ui.py
git commit -m "feat(settings): hot-reload MCP servers, skill markets, monitoring"
```

---

## Task 14: Approval integration for admin-only and credential keys

**Files:**
- Create: `src/breadmind/settings/approval_queue.py`
- Modify: `src/breadmind/settings/service.py`
- Test: `tests/settings/test_settings_service_approval.py`

- [ ] **Step 1: Write failing approval test**

Create `tests/settings/test_settings_service_approval.py`:

```python
import pytest

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/settings/test_settings_service_approval.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement PendingApprovalQueue**

Create `src/breadmind/settings/approval_queue.py`:

```python
"""In-memory queue of pending settings writes awaiting user approval.

Each entry captures the bound callable and its keyword arguments so that
``resolve(id)`` can execute the original intent exactly once.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class PendingEntry:
    id: str
    purpose: str
    key: str
    actor: str
    run: Callable[[], Awaitable[Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


class PendingApprovalQueue:
    def __init__(self) -> None:
        self._entries: dict[str, PendingEntry] = {}

    def submit(
        self,
        *,
        purpose: str,
        key: str,
        actor: str,
        run: Callable[[], Awaitable[Any]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        approval_id = f"approve-{uuid.uuid4().hex[:8]}"
        self._entries[approval_id] = PendingEntry(
            id=approval_id,
            purpose=purpose,
            key=key,
            actor=actor,
            run=run,
            metadata=dict(metadata or {}),
        )
        return approval_id

    async def resolve(self, approval_id: str) -> Any:
        entry = self._entries.pop(approval_id, None)
        if entry is None:
            raise KeyError(approval_id)
        return await entry.run()

    def list_pending(self) -> list[PendingEntry]:
        return list(self._entries.values())
```

- [ ] **Step 4: Wire approval into SettingsService**

Modify `src/breadmind/settings/service.py`:

1. Add `approval_queue` parameter to `__init__`:

```python
    def __init__(
        self,
        *,
        store,
        vault,
        audit_sink,
        reload_registry,
        event_bus=None,
        approval_queue=None,
    ) -> None:
        self._store = store
        self._vault = vault
        self._audit_sink = audit_sink
        self._registry = reload_registry
        self._bus = event_bus
        self._approvals = approval_queue
        self._key_locks: dict[str, asyncio.Lock] = {}
```

2. Add the admin-key constant at module level (mirror the set in `actions.py`):

```python
_ADMIN_ONLY_KEYS: frozenset[str] = frozenset({
    "safety_blacklist",
    "safety_approval",
    "safety_permissions",
    "safety_permissions_admin_users",
    "tool_security",
    "system_timeouts",
    "retry_config",
    "limits_config",
    "polling_config",
    "agent_timeouts",
    "logging_config",
})
```

3. Add a gate helper:

```python
    def _requires_approval(self, key: str, actor: str) -> bool:
        if not actor.startswith("agent:"):
            return False
        if self._approvals is None:
            return False
        if settings_schema.is_credential_key(key):
            return True
        return key in _ADMIN_ONLY_KEYS
```

4. At the start of each write method (`set`, `append`, `update_item`, `delete_item`, `set_credential`, `delete_credential`), after the `is_allowed_key` check, add:

```python
        if self._requires_approval(key, actor):
            async def _run():
                return await self._set_internal(key, value, actor=actor)  # adjust per-method
            approval_id = self._approvals.submit(
                purpose=f"settings_{operation}",
                key=key,
                actor=actor,
                run=_run,
            )
            return SetResult(
                ok=False,
                operation=operation,
                key=key,
                pending_approval_id=approval_id,
            )
```

The cleanest implementation factors the existing body of each method into a private `_set_internal(key, value, *, actor)` (and the analogous `_append_internal`, `_update_item_internal`, etc.) so the approval path can capture them as closures. Each public method then looks like:

```python
    async def set(self, key: str, value: Any, *, actor: str) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="set", key=key, error=f"key '{key}' is not allowed")
        if self._requires_approval(key, actor):
            async def _run():
                return await self._set_internal(key, value, actor=actor)
            approval_id = self._approvals.submit(
                purpose="settings_set", key=key, actor=actor, run=_run,
            )
            return SetResult(ok=False, operation="set", key=key, pending_approval_id=approval_id)
        return await self._set_internal(key, value, actor=actor)
```

Apply the same refactor to all six write methods. `_set_internal` etc. contain what `set`, `append`, … currently do after the allowed-key check.

5. Add the resolve method:

```python
    async def resolve_approval(self, approval_id: str) -> SetResult:
        if self._approvals is None:
            return SetResult(
                ok=False, operation="resolve_approval", key="",
                error="approval queue not configured",
            )
        try:
            return await self._approvals.resolve(approval_id)
        except KeyError:
            return SetResult(
                ok=False, operation="resolve_approval", key="",
                error=f"unknown approval id: {approval_id}",
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/settings/test_settings_service_approval.py tests/settings/test_settings_service.py tests/settings/test_settings_service_events.py -v`
Expected: all pre-existing passes + 5 new = green

- [ ] **Step 6: Wire approval queue into the web app**

In `src/breadmind/web/routes/ui.py`, inside `_ensure_projector`, replace the `SettingsService(...)` constructor call to pass a shared `PendingApprovalQueue`:

```python
        from breadmind.settings.approval_queue import PendingApprovalQueue
        approval_queue = PendingApprovalQueue()
        settings_service = SettingsService(
            store=settings_store,
            vault=credential_vault,
            audit_sink=None,  # back-filled after ActionHandler
            reload_registry=reload_registry,
            event_bus=flow_bus,
            approval_queue=approval_queue,
        )
        app.state.settings_approval_queue = approval_queue
```

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest tests/ -v -x --tb=short`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/breadmind/settings/approval_queue.py src/breadmind/settings/service.py tests/settings/test_settings_service_approval.py src/breadmind/web/routes/ui.py
git commit -m "feat(settings): gate admin/credential writes behind approval queue"
```

---

## Task 15: Per-actor rate limiting

**Files:**
- Create: `src/breadmind/settings/rate_limiter.py`
- Modify: `src/breadmind/settings/service.py`
- Test: `tests/settings/test_settings_service_rate_limit.py`

- [ ] **Step 1: Write failing test**

Create `tests/settings/test_settings_service_rate_limit.py`:

```python
import time

from breadmind.settings.rate_limiter import SlidingWindowRateLimiter
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService


class FakeStore:
    def __init__(self):
        self.data = {"persona": "professional"}
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
    r1 = await svc.set("persona", "friendly", actor="agent:core")
    assert r1.ok is True
    r2 = await svc.set("persona", "concise", actor="agent:core")
    assert r2.ok is False
    assert "rate limit" in (r2.error or "").lower()


async def test_user_actor_exempt_from_rate_limit():
    limiter = SlidingWindowRateLimiter(window_seconds=60, max_events=1)
    svc = _build(limiter)
    await svc.set("persona", "friendly", actor="user:alice")
    r = await svc.set("persona", "concise", actor="user:alice")
    assert r.ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/settings/test_settings_service_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the rate limiter**

Create `src/breadmind/settings/rate_limiter.py`:

```python
"""Simple sliding-window rate limiter scoped by actor id."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, *, window_seconds: float = 60.0, max_events: int = 20) -> None:
        self._window = float(window_seconds)
        self._max = int(max_events)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, actor: str, *, now: float | None = None) -> bool:
        """Return True if this event is allowed; False if the actor is over cap."""
        ts = time.monotonic() if now is None else float(now)
        q = self._events[actor]
        cutoff = ts - self._window
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= self._max:
            return False
        q.append(ts)
        return True
```

- [ ] **Step 4: Wire the limiter into SettingsService**

In `src/breadmind/settings/service.py` add `rate_limiter` to `__init__`:

```python
    def __init__(
        self,
        *,
        store,
        vault,
        audit_sink,
        reload_registry,
        event_bus=None,
        approval_queue=None,
        rate_limiter=None,
    ) -> None:
        ...
        self._rate_limiter = rate_limiter
```

Add a helper and call it at the top of each write-internal method (just after the approval gate — or add a shared entry point before the allowed-key check):

```python
    def _check_rate(self, actor: str, operation: str, key: str) -> SetResult | None:
        if self._rate_limiter is None:
            return None
        if not actor.startswith("agent:"):
            return None
        if self._rate_limiter.check(actor):
            return None
        return SetResult(
            ok=False,
            operation=operation,
            key=key,
            error=f"rate limit exceeded for {actor}",
        )
```

Insert this check at the start of each public write method:

```python
    async def set(self, key: str, value: Any, *, actor: str) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(ok=False, operation="set", key=key, error=f"key '{key}' is not allowed")
        rl = self._check_rate(actor, "set", key)
        if rl is not None:
            return rl
        if self._requires_approval(key, actor):
            ...
        return await self._set_internal(key, value, actor=actor)
```

Repeat for `append`, `update_item`, `delete_item`, `set_credential`, `delete_credential`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/settings/test_settings_service_rate_limit.py tests/settings/ -v`
Expected: all green.

- [ ] **Step 6: Wire the limiter into the web app**

In `src/breadmind/web/routes/ui.py`, change the `SettingsService` construction to include the limiter:

```python
        from breadmind.settings.rate_limiter import SlidingWindowRateLimiter
        rate_limiter = SlidingWindowRateLimiter(window_seconds=60, max_events=20)
        settings_service = SettingsService(
            store=settings_store,
            vault=credential_vault,
            audit_sink=None,
            reload_registry=reload_registry,
            event_bus=flow_bus,
            approval_queue=approval_queue,
            rate_limiter=rate_limiter,
        )
        app.state.settings_rate_limiter = rate_limiter
```

- [ ] **Step 7: Run full suite**

Run: `python -m pytest tests/ -v -x --tb=short`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/breadmind/settings/rate_limiter.py src/breadmind/settings/service.py tests/settings/test_settings_service_rate_limit.py src/breadmind/web/routes/ui.py
git commit -m "feat(settings): enforce per-actor write rate limit"
```

---

## Task 16: End-to-end integration test

**Files:**
- Test: `tests/settings/test_end_to_end.py`

- [ ] **Step 1: Write the integration test**

Create `tests/settings/test_end_to_end.py`:

```python
"""Full-stack smoke test: agent tool call → SettingsService → hot reload."""
from breadmind.core.events import EventBus, EventType
from breadmind.settings.llm_holder import LLMProviderHolder
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService
from breadmind.settings.approval_queue import PendingApprovalQueue
from breadmind.tools.registry import ToolRegistry
from breadmind.tools.settings_tool_registration import register_settings_tools


class InMemoryStore:
    def __init__(self, data=None):
        self.data = dict(data or {})
    async def get_setting(self, key):
        return self.data.get(key)
    async def set_setting(self, key, value):
        self.data[key] = value
    async def delete_setting(self, key):
        self.data.pop(key, None)


class InMemoryVault:
    def __init__(self):
        self.store = {}
    async def store(self, cred_id, value, metadata=None):
        self.store[cred_id] = value
        return cred_id
    async def delete(self, cred_id):
        self.store.pop(cred_id, None)
        return True


async def _noop(**kwargs):
    return 1


class FakeProvider:
    def __init__(self, name):
        self.name = name


async def test_agent_tool_call_hot_reloads_llm_provider():
    bus = EventBus()
    events = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    store = InMemoryStore({"llm": {"default_provider": "claude"}})
    vault = InMemoryVault()
    registry = SettingsReloadRegistry()
    service = SettingsService(
        store=store,
        vault=vault,
        audit_sink=_noop,
        reload_registry=registry,
        event_bus=bus,
        approval_queue=PendingApprovalQueue(),
    )

    holder = LLMProviderHolder(FakeProvider("claude"))

    async def _reload_llm(ctx):
        # Real factory would use create_provider(ctx['new']); stub it here.
        holder.swap(FakeProvider(ctx["new"]["default_provider"]))

    registry.register("llm", _reload_llm)

    tool_registry = ToolRegistry()
    register_settings_tools(tool_registry, service=service, actor="agent:core")

    # Look up the tool callable.
    fn = tool_registry.get_tool_fn("breadmind_set_setting")  # or equivalent accessor
    result = await fn(key="llm", value='{"default_provider":"gemini","default_model":"gemini-2.0-flash"}')

    assert result.startswith("OK")
    assert "hot_reloaded=true" in result
    assert holder.name == "gemini"
    assert len(events) == 1
    assert events[0]["key"] == "llm"
    assert events[0]["actor"] == "agent:core"
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/settings/test_end_to_end.py -v`
Expected: 1 passed. If `ToolRegistry.get_tool_fn` is not the real method name, substitute whichever accessor `src/breadmind/tools/registry.py` actually exposes for retrieving a registered callable by name.

- [ ] **Step 3: Run the full suite as a final gate**

Run: `python -m pytest tests/ --tb=short`
Expected: every test green. Count the total and compare against the pre-task 6 baseline plus the new tests added in this plan: there should be at least `baseline + (5+7+5+3+2+1+10+2+3+1+1+2+3+5+3+1) = baseline + 54` passing tests.

- [ ] **Step 4: Commit**

```bash
git add tests/settings/test_end_to_end.py
git commit -m "test(settings): end-to-end hot-reload smoke test"
```

---

## Self-Review Checklist

Before handing off to execution, the implementer should confirm:

1. **Every hot-reloadable key from `settings_schema.py` has a subscriber registered in Tasks 9–13.** The full key list: `llm`, `persona`, `custom_prompts`, `custom_instructions`, `apikey:*`, `mcp`, `mcp_servers`, `skill_markets`, `safety_blacklist`, `safety_approval`, `safety_permissions`, `safety_permissions_admin_users`, `tool_security`, `monitoring_config`, `loop_protector`, `scheduler_cron`, `webhook_endpoints`, `memory_gc_config`, `retry_config`, `limits_config`, `polling_config`, `agent_timeouts`, `system_timeouts`, `logging_config`. The only intentionally unsubscribed key is `embedding_config` (restart required).

2. **`ActionHandler` behaviour is byte-compatible with the pre-refactor SDUI tests.** Task 6 asserts the full suite stays green.

3. **No plaintext credentials are emitted through `EventType.SETTINGS_CHANGED`.** Task 5's second test covers this.

4. **Agent actor cannot bootstrap its way into admin.** The `safety_permissions_admin_users` bootstrap exception lives in `ActionHandler._settings_append` for `user:*` actors only. `SettingsService._requires_approval` makes every `agent:*` write to this key go through approval.

5. **Per-key locks serialize writes to the same key.** Tests add `asyncio.gather` races as a follow-up if flakiness surfaces.

6. **Rate-limit defaults are tunable.** Task 15 hard-codes 20 writes/minute for agent actors. A later PR can promote this to a settings key once the pattern proves itself; it is intentionally not a setting in this round to avoid the "agent raises its own limit" recursion.

## Out of Scope for this Plan

- Rewriting SafetyGuard internals beyond adding `reload()`.
- Cross-process hot reload (only the local process reloads).
- Promoting `settings_write_rate_limit` to a settings key.
- New UI affordances beyond the existing settings page.
- Replacing the in-memory approval queue with a persistent store.
