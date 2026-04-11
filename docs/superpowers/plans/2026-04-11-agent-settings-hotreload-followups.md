# Agent Settings Hot-Reload — Follow-up Cleanup Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the tech-debt items flagged during the 2026-04-11 hot-reload implementation — remove the `_rewrite_last_audit` smell, delete dead fallback paths in `ActionHandler`, extract the settings pipeline wiring out of `_ensure_projector`, and replace the three reloader `getattr` fallbacks with real `apply_*` methods on the MCP, plugin, and monitoring managers. Also adds `custom_prompts` to `PromptContext` so the already-wired subscriber actually affects the rendered system prompt.

**Architecture:** Each task is an independent refactor within the existing `SettingsService` / `SettingsReloadRegistry` pipeline. No new pipelines are introduced. The goal is to make the existing code pay back the compatibility band-aids applied while the 542 pre-existing SDUI tests were kept green.

**Tech Stack:** Python 3.12+, asyncio, pytest-asyncio (auto mode), existing EventBus, existing MCP/plugin/monitoring subsystems, Jinja2 prompt templates.

**Parent plan:** `docs/superpowers/plans/2026-04-11-agent-settings-hotreload.md`
**Parent spec:** `docs/superpowers/specs/2026-04-11-agent-settings-hotreload-design.md`

---

## File Structure

**Modified files:**
- `src/breadmind/settings/service.py` — add `audit_key` and `audit_kind` optional kwargs to `set/append/update_item/delete_item` so the translator can override the audit-log key and action kind when the storage key differs from the SDUI-facing key.
- `src/breadmind/sdui/actions.py` — remove dead fallback paths (`if self._settings_service is None:` branches), remove helpers that are only reachable through them (`_append_blacklist_entry`, `_append_admin_user`, the `_merge_*` static methods that the new translator doesn't use), and delete `_rewrite_last_audit` in favor of the new `audit_key`/`audit_kind` pipe.
- `src/breadmind/web/routes/ui.py` — extract the ~320-line settings wiring block from `_ensure_projector` into a new private helper module.
- `src/breadmind/mcp/server_manager.py` — add `apply_config(mcp_cfg=None, servers=None)` that reconciles `self._servers` against the new `mcp_servers` setting.
- `src/breadmind/plugins/manager.py` — add `apply_markets(markets)` that stores the new market list on `self._markets_config` and logs a best-effort info message (full marketplace sync is out of scope — this task only closes the no-op hole in the reloader chain).
- `src/breadmind/monitoring/engine.py` — add `apply(monitoring_config=None, loop_protector=None, scheduler_cron=None, webhook_endpoints=None)` that delegates to existing `update_loop_protector_config` / `enable_rule` / `disable_rule` / `update_rule_interval` for the fields that have working paths, and logs debug for the fields that don't.
- `src/breadmind/prompts/builder.py` — add `custom_prompts: dict[str, str] | None = None` field to `PromptContext` and accept it in `PromptBuilder.build(...)`.

**New files:**
- `src/breadmind/web/settings_wiring.py` — extracted `build_settings_pipeline(...)` helper that `_ensure_projector` calls.

**New test files:**
- `tests/settings/test_audit_key_override.py`
- `tests/settings/test_web_settings_wiring.py`
- `tests/mcp/test_server_manager_apply_config.py`
- `tests/plugins/test_manager_apply_markets.py`
- `tests/monitoring/test_engine_apply.py`
- `tests/prompts/test_prompt_builder_custom_prompts.py`

---

## Conventions

All tests use `pytest-asyncio` auto mode. Every task ends with:

```bash
python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py -q
```

and must report **no regressions** from the 940-test baseline at commit `3089a97` (the Task 16 E2E commit on the parent plan). Targeted tests run first to verify the new behavior, then the full relevant zone runs to catch regressions, then commit.

Commit messages follow the pattern of the parent plan (`feat(scope):`, `refactor(scope):`, `fix(scope):`, `test(scope):`).

---

## Task 1: `audit_key` + `audit_kind` override — remove `_rewrite_last_audit`

**Problem:** `ActionHandler` has a `_rewrite_last_audit(*, action_key, key)` helper that mutates the last audit entry *after* `SettingsService.set(...)` already persisted and dispatched. This is used when the SDUI action targets `safety_permissions_admin_users` but the storage key is `safety_permissions` — the translator calls `service.set("safety_permissions", ...)` then rewrites the audit row to say `key="safety_permissions_admin_users"` and `kind="settings_append"`. This is racy (TOCTOU between service writing the audit row and translator rewriting it) and inconsistent with the `SETTINGS_CHANGED` event, which still carries the storage key.

**Solution:** Add `audit_key` and `audit_kind` optional kwargs to `SettingsService.set` (and the list methods, in case a future caller needs them). The service honors them when building the audit payload but keeps the real storage key for dispatch/event emission. Translator stops calling `_rewrite_last_audit`. Helper is deleted.

**Files:**
- Modify: `src/breadmind/settings/service.py`
- Modify: `src/breadmind/sdui/actions.py`
- Test: `tests/settings/test_audit_key_override.py`

- [ ] **Step 1: Write the failing test**

Create `tests/settings/test_audit_key_override.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/settings/test_audit_key_override.py -v`
Expected: FAIL with `TypeError: _set_internal() got an unexpected keyword argument 'audit_key'` (or `set()` if the public method is reached first).

- [ ] **Step 3: Thread `audit_key` / `audit_kind` through `SettingsService.set`**

In `src/breadmind/settings/service.py`, update both `set(...)` and `_set_internal(...)` signatures:

```python
    async def set(
        self,
        key: str,
        value: Any,
        *,
        actor: str,
        audit_summary: str | None = None,
        audit_key: str | None = None,
        audit_kind: str | None = None,
    ) -> SetResult:
        if not settings_schema.is_allowed_key(key):
            return SetResult(
                ok=False, operation="set", key=key,
                error=f"key '{key}' is not allowed",
            )
        rl = self._check_rate(actor, "set", key)
        if rl is not None:
            return rl
        if self._requires_approval(key, actor):
            async def _run() -> SetResult:
                return await self._set_internal(
                    key, value,
                    actor=actor,
                    audit_summary=audit_summary,
                    audit_key=audit_key,
                    audit_kind=audit_kind,
                )
            approval_id = self._approvals.submit(
                purpose="settings_set", key=key, actor=actor, run=_run,
            )
            return SetResult(
                ok=False, operation="set", key=key,
                pending_approval_id=approval_id,
            )
        return await self._set_internal(
            key, value,
            actor=actor,
            audit_summary=audit_summary,
            audit_key=audit_key,
            audit_kind=audit_kind,
        )

    async def _set_internal(
        self,
        key: str,
        value: Any,
        *,
        actor: str,
        audit_summary: str | None = None,
        audit_key: str | None = None,
        audit_kind: str | None = None,
    ) -> SetResult:
        try:
            normalized = settings_schema.validate_value(key, value)
        except settings_schema.SettingsValidationError as exc:
            return SetResult(
                ok=False, operation="set", key=key,
                error=f"validation failed — {exc}",
            )
        async with self._lock(key):
            old = await self._store.get_setting(key)
            await self._store.set_setting(key, normalized)
            audit_id = await self._audit_sink(
                kind=audit_kind or "settings_write",
                key=audit_key or key,
                actor=actor,
                old_preview=old,
                new_preview=normalized,
                summary=audit_summary,
            )
            dispatch = await self._registry.dispatch(
                key=key, operation="set", old=old, new=normalized
            )
            event_payload = self._build_event_payload(
                key=key, operation="set", old=old, new=normalized,
                actor=actor, audit_id=audit_id,
            )
        await self._emit_payload(event_payload)
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

Note: `dispatch` and `event_payload` still use the **real storage key**, not `audit_key`. The override is audit-only. Subscribers and event listeners see the authoritative key.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/settings/test_audit_key_override.py -v`
Expected: 2 passed.

- [ ] **Step 5: Migrate ActionHandler translators to pass `audit_key`/`audit_kind`**

In `src/breadmind/sdui/actions.py`, find the two call sites that currently delegate through `_rewrite_last_audit`:

1. The `safety_permissions_admin_users` branch inside `_settings_append`. Replace the post-hoc audit rewrite with direct overrides on the `SettingsService.set` call:

```python
            result = await self._settings_service.set(
                "safety_permissions",
                merged_permissions,
                actor=f"user:{user_id}",
                audit_summary=summary,
                audit_key="safety_permissions_admin_users",
                audit_kind="settings_append",
            )
            # No _rewrite_last_audit call here.
```

2. The `safety_blacklist` branch inside `_settings_append`. Same pattern:

```python
            result = await self._settings_service.set(
                "safety_blacklist",
                merged_blacklist,
                actor=f"user:{user_id}",
                audit_summary=summary,
                audit_key="safety_blacklist",
                audit_kind="settings_append",
            )
```

(The storage key equals the SDUI key here, but the `kind` still needs to be `settings_append` instead of `settings_write`, so the override earns its keep.)

3. Delete the `_rewrite_last_audit` method entirely. Grep `src/breadmind/sdui/` for any other caller — there should be none after step 5.2. If a caller is found, report BLOCKED.

- [ ] **Step 6: Run the full SDUI + settings suite**

Run: `python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py -q`
Expected: 940 + 2 new = 942 passed. Zero regressions. If any SDUI test that asserts on `entry["kind"]` or `entry["key"]` fails, that's the signal that the override wiring is off — debug before committing.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/settings/service.py src/breadmind/sdui/actions.py tests/settings/test_audit_key_override.py
git commit -m "refactor(settings): audit_key/audit_kind overrides replace _rewrite_last_audit"
```

---

## Task 2: Delete ActionHandler dead fallback paths

**Problem:** `ActionHandler._settings_append` and `_settings_update_item` each have an `if self._settings_service is None:` branch that runs the pre-refactor direct-store logic. Because `__init__` always auto-constructs a `SettingsService` when `settings_store is not None`, those branches are unreachable under normal construction. Only a silently-caught construction failure could hit them, and the safe thing there is to fail fast rather than silently lose hot-reload guarantees.

The fallback branches drag along helpers that are only used by them: `_append_blacklist_entry`, `_append_admin_user`, and the `_merge_*` static methods. Total: ~150 lines of dead code.

**Solution:** Delete the fallback branches. Delete the helpers. Make the `SettingsService` requirement explicit in `__init__` by asserting after auto-construction — if somehow a caller passed `settings_store=None, settings_service=None`, fail fast with a `RuntimeError` instead of silently degrading.

**Files:**
- Modify: `src/breadmind/sdui/actions.py`

- [ ] **Step 1: Baseline the SDUI suite**

Run: `python -m pytest tests/sdui/ -q --tb=no`
Expected: 543 passed (or whatever the current count is). Record the number.

- [ ] **Step 2: Find every `_settings_service is None` branch**

Run: `grep -n "_settings_service is None" src/breadmind/sdui/actions.py`
Expected: 4-5 line numbers. Note them.

- [ ] **Step 3: Replace each fallback block with a defensive `RuntimeError`**

For each `if self._settings_service is None:` block inside a write method, delete the fallback body and replace with:

```python
        if self._settings_service is None:
            raise RuntimeError(
                "ActionHandler.settings_service is None — construction failed "
                "or bypassed. Reload pipeline is not available.",
            )
```

This is a temporary guard — step 5 removes it entirely once the construction is hardened.

- [ ] **Step 4: Delete the helpers that only the fallbacks used**

Delete these methods from `src/breadmind/sdui/actions.py`:
- `_append_blacklist_entry` (around line 1145)
- `_append_admin_user` (around line 1187)
- The `_merge_*` static methods in the 1090-1143 range that the new translator path does NOT use (`_merge_mcp_server`, `_merge_skill_market`, `_merge_safety_approval`, `_merge_scheduler_cron`)

**Before deleting a helper, grep for it across the whole codebase:**
```bash
grep -rn "_append_blacklist_entry\|_append_admin_user\|_merge_mcp_server\|_merge_skill_market\|_merge_safety_approval\|_merge_scheduler_cron" src/breadmind/ tests/
```

If any non-test caller outside `actions.py` shows up, STOP and report — that helper is actually reachable and should not be deleted. If only callers inside the deleted fallback blocks show up, the helper is confirmed dead and safe to remove.

The new translator path uses `_prepare_*_item` helpers (introduced in the parent plan's Task 6) — do NOT delete those.

- [ ] **Step 5: Harden `ActionHandler.__init__` so the service is always constructed**

In `src/breadmind/sdui/actions.py`, locate the `__init__` auto-construction block:

```python
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

Replace with a strict version that fails fast if no service can be built:

```python
        if settings_service is None:
            if settings_store is None:
                # No service and no store — legacy tests that only exercise
                # non-settings actions (intervention/etc.) construct the
                # handler without either. Accept the None and have the write
                # methods raise if they are called.
                self._settings_service = None
            else:
                from breadmind.settings.reload_registry import SettingsReloadRegistry
                from breadmind.settings.service import SettingsService
                self._settings_service = SettingsService(
                    store=settings_store,
                    vault=credential_vault,
                    audit_sink=self._record_audit,
                    reload_registry=SettingsReloadRegistry(),
                    event_bus=event_bus,
                )
        else:
            self._settings_service = settings_service
```

The guards added in Step 3 now catch the legitimate "no settings_store at all" case with a clear RuntimeError instead of silently ignoring the write. That is the right behavior: if a test/deployment constructs an ActionHandler without a settings store and then tries to perform a settings write, that's a programming error.

- [ ] **Step 6: Run the full SDUI + settings suite**

Run: `python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py -q`
Expected: 942 passed. If any test that previously constructed `ActionHandler(bus=..., settings_store=None, ...)` and then called a settings action now fails with `RuntimeError`, inspect it — it may be a test that always had an unreachable code path, in which case the test itself is the bug and should be updated (or the test's settings_store should be a real fake).

If you have to update a test: only adjust the fixture to provide a real fake store. **Do NOT** change assertions to tolerate the RuntimeError.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/sdui/actions.py
git commit -m "refactor(sdui): delete dead ActionHandler fallback paths + unused helpers"
```

---

## Task 3: Extract `build_settings_pipeline` helper

**Problem:** `_ensure_projector` in `src/breadmind/web/routes/ui.py` is ~439 lines and does seven unrelated wiring jobs. The settings-hot-reload wiring alone is ~320 lines of that. It's hard to read, hard to unit-test, and the next feature that needs to wire a subscriber will push it over 500.

**Solution:** Extract a new module `src/breadmind/web/settings_wiring.py` with a single `build_settings_pipeline(...)` function that takes the dependencies and returns a `SettingsPipeline` dataclass holding everything the web app needs to stash on `app.state`. `_ensure_projector` becomes a thin caller.

**Files:**
- Create: `src/breadmind/web/settings_wiring.py`
- Modify: `src/breadmind/web/routes/ui.py`
- Test: `tests/settings/test_web_settings_wiring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/settings/test_web_settings_wiring.py`:

```python
from breadmind.core.events import EventBus
from breadmind.web.settings_wiring import (
    SettingsPipeline,
    build_settings_pipeline,
)


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
    async def store(self, *a, **k):
        return "x"

    async def delete(self, *a, **k):
        return True


async def test_build_settings_pipeline_assembles_full_stack():
    flow_bus = EventBus()
    store = FakeStore({"llm": {"default_provider": "claude"}})
    vault = FakeVault()

    pipeline = await build_settings_pipeline(
        flow_bus=flow_bus,
        settings_store=store,
        credential_vault=vault,
        message_handler=None,
        working_memory=None,
    )

    assert isinstance(pipeline, SettingsPipeline)
    assert pipeline.reload_registry is not None
    assert pipeline.settings_service is not None
    assert pipeline.action_handler is not None
    assert pipeline.approval_queue is not None
    assert pipeline.rate_limiter is not None
    # Runtime holder is seeded from the store (even if only llm is present,
    # none of the 7 runtime keys are so it stays empty).
    assert pipeline.runtime_config_holder is not None

    # Audit sink back-fill happened: service routes through action_handler.
    assert (
        pipeline.settings_service._audit_sink
        == pipeline.action_handler._record_audit
    )


async def test_build_settings_pipeline_seeds_runtime_config_from_store():
    store = FakeStore({
        "retry_config": {"max_attempts": 5},
        "logging_config": {"level": "INFO"},
    })
    pipeline = await build_settings_pipeline(
        flow_bus=EventBus(),
        settings_store=store,
        credential_vault=FakeVault(),
        message_handler=None,
        working_memory=None,
    )
    assert pipeline.runtime_config_holder.get("retry_config") == {"max_attempts": 5}
    assert pipeline.runtime_config_holder.get("logging_config") == {"level": "INFO"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/settings/test_web_settings_wiring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'breadmind.web.settings_wiring'`

- [ ] **Step 3: Extract the helper**

Create `src/breadmind/web/settings_wiring.py`:

```python
"""Assemble the SettingsService + reload pipeline for the web app.

Extracted from ``_ensure_projector`` so its 300+ lines of wiring live in a
dedicated module that can be unit-tested without a full web app fixture.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from breadmind.sdui.actions import ActionHandler
from breadmind.settings.approval_queue import PendingApprovalQueue
from breadmind.settings.rate_limiter import SlidingWindowRateLimiter
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.runtime_config import RuntimeConfigHolder
from breadmind.settings.service import SettingsService

logger = logging.getLogger(__name__)


@dataclass
class SettingsPipeline:
    """Everything the web app stashes on ``app.state`` for settings writes."""
    reload_registry: SettingsReloadRegistry
    settings_service: SettingsService
    action_handler: ActionHandler
    approval_queue: PendingApprovalQueue
    rate_limiter: SlidingWindowRateLimiter
    runtime_config_holder: RuntimeConfigHolder


_RUNTIME_CONFIG_KEYS = (
    "retry_config",
    "limits_config",
    "polling_config",
    "agent_timeouts",
    "system_timeouts",
    "logging_config",
    "memory_gc_config",
)


async def build_settings_pipeline(
    *,
    flow_bus: Any,
    settings_store: Any,
    credential_vault: Any,
    message_handler: Any,
    working_memory: Any,
) -> SettingsPipeline:
    """Build the full settings pipeline from the provided dependencies.

    Returns a :class:`SettingsPipeline` the caller can unpack into
    ``app.state.*``. The caller is responsible for registering any component-
    specific reloaders (LLM holder, safety guard, etc.) on
    ``pipeline.reload_registry`` afterwards.
    """
    reload_registry = SettingsReloadRegistry()
    approval_queue = PendingApprovalQueue()
    rate_limiter = SlidingWindowRateLimiter(window_seconds=60, max_events=20)

    async def _placeholder_audit(**_kwargs):
        return None

    settings_service = SettingsService(
        store=settings_store,
        vault=credential_vault,
        audit_sink=_placeholder_audit,
        reload_registry=reload_registry,
        event_bus=flow_bus,
        approval_queue=approval_queue,
        rate_limiter=rate_limiter,
    )

    action_handler = ActionHandler(
        bus=flow_bus,
        message_handler=message_handler,
        working_memory=working_memory,
        settings_store=settings_store,
        credential_vault=credential_vault,
        event_bus=flow_bus,
        settings_service=settings_service,
    )
    settings_service.set_audit_sink(action_handler._record_audit)

    initial_runtime: dict[str, Any] = {}
    for key in _RUNTIME_CONFIG_KEYS:
        try:
            val = await settings_store.get_setting(key)
        except Exception:  # noqa: BLE001
            val = None
        if val is not None:
            initial_runtime[key] = val
    runtime_config_holder = RuntimeConfigHolder(initial=initial_runtime)
    runtime_config_holder.register(reload_registry)

    return SettingsPipeline(
        reload_registry=reload_registry,
        settings_service=settings_service,
        action_handler=action_handler,
        approval_queue=approval_queue,
        rate_limiter=rate_limiter,
        runtime_config_holder=runtime_config_holder,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/settings/test_web_settings_wiring.py -v`
Expected: 2 passed.

- [ ] **Step 5: Rewire `_ensure_projector` to call the helper**

In `src/breadmind/web/routes/ui.py`, replace the block from the `# Shared SettingsService...` comment (around line 135) through the end of the `app.state.runtime_config_holder = ...` block (around line 376 — covering all of Tasks 6, 12 wiring) with:

```python
        from breadmind.web.settings_wiring import build_settings_pipeline
        pipeline = await build_settings_pipeline(
            flow_bus=flow_bus,
            settings_store=settings_store,
            credential_vault=credential_vault,
            message_handler=message_handler,
            working_memory=working_memory,
        )
        app.state.settings_reload_registry = pipeline.reload_registry
        app.state.settings_service = pipeline.settings_service
        app.state.settings_approval_queue = pipeline.approval_queue
        app.state.settings_rate_limiter = pipeline.rate_limiter
        app.state.runtime_config_holder = pipeline.runtime_config_holder
        app.state.sdui_action_handler = pipeline.action_handler

        # Locals below reference these so the existing component-reloader
        # blocks (LLM, persona, safety, MCP, plugin, monitoring) can remain
        # in place without changes for this task.
        reload_registry = pipeline.reload_registry
        settings_service = pipeline.settings_service
        action_handler = pipeline.action_handler
```

The component-specific reloader blocks (LLM holder, persona, SafetyGuard, MCP, plugin manager, monitoring) stay in `_ensure_projector` for this task — Task 3 only extracts the *generic* pipeline construction, not the per-component wiring. Pushing the component wiring into separate helpers is future cleanup.

- [ ] **Step 6: Run the full relevant suite**

Run: `python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py -q`
Expected: 942 + 2 new = 944 passed.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/web/settings_wiring.py src/breadmind/web/routes/ui.py tests/settings/test_web_settings_wiring.py
git commit -m "refactor(web): extract build_settings_pipeline out of _ensure_projector"
```

---

## Task 4: `MCPServerManager.apply_config` — replace getattr fallback

**Problem:** The reloader registered in `_ensure_projector` for `mcp` / `mcp_servers` keys is a `getattr(mcp_manager_obj, "apply_config", None)` + event-bus fallback. Because `MCPServerManager` has no `apply_config` method today, every MCP settings write silently falls back to emitting a legacy event and relying on the existing event handler — which exists, but is not the contract the plan intended.

**Solution:** Implement `MCPServerManager.apply_config(*, mcp_cfg=None, servers=None)` that reconciles `self._servers` against the new server list using `add_server` / `remove_server` / `restart_server`. The `mcp_cfg` parameter (global MCP config like `auto_discover`) is stored on a new `self._global_config` attribute; a debug log acknowledges that dynamic auto-discover toggling is out of scope for this task.

**Files:**
- Modify: `src/breadmind/mcp/server_manager.py`
- Modify: `src/breadmind/web/routes/ui.py`
- Test: `tests/mcp/test_server_manager_apply_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/mcp/test_server_manager_apply_config.py`:

```python
from unittest.mock import AsyncMock

from breadmind.core.events import EventBus
from breadmind.mcp.server_manager import MCPServerManager


def _make_manager(monkeypatch):
    mgr = MCPServerManager(event_bus=EventBus())
    # Stub out add_server / remove_server so tests don't actually launch MCP.
    mgr.add_server = AsyncMock()
    mgr.remove_server = AsyncMock()
    mgr.restart_server = AsyncMock()
    return mgr


async def test_apply_config_adds_new_servers(monkeypatch):
    mgr = _make_manager(monkeypatch)
    await mgr.apply_config(servers=[
        {"name": "github", "command": "npx", "args": ["-y", "gh"], "env": {}, "enabled": True},
        {"name": "local", "command": "python", "args": ["-m", "l"], "env": {}, "enabled": True},
    ])
    names_added = [c.args[0].name for c in mgr.add_server.call_args_list]
    assert set(names_added) == {"github", "local"}
    mgr.remove_server.assert_not_called()


async def test_apply_config_removes_disappeared_servers(monkeypatch):
    mgr = _make_manager(monkeypatch)
    # Seed the manager with a fake running server.
    from breadmind.mcp.server_manager import MCPServerState
    mgr._servers["stale"] = MCPServerState(
        name="stale", config=None, process=None, tools=[],
    )
    await mgr.apply_config(servers=[
        {"name": "github", "command": "npx", "args": [], "env": {}, "enabled": True},
    ])
    mgr.remove_server.assert_awaited_once_with("stale")
    names_added = [c.args[0].name for c in mgr.add_server.call_args_list]
    assert names_added == ["github"]


async def test_apply_config_restarts_changed_enabled_servers(monkeypatch):
    mgr = _make_manager(monkeypatch)
    from breadmind.mcp.server_manager import MCPServerConfig, MCPServerState
    existing_cfg = MCPServerConfig(
        name="github", command="npx", args=["-y", "gh"], env={}, enabled=True,
    )
    mgr._servers["github"] = MCPServerState(
        name="github", config=existing_cfg, process=None, tools=[],
    )
    # New payload: same name, different command (treat as config change).
    await mgr.apply_config(servers=[
        {"name": "github", "command": "uvx", "args": ["gh"], "env": {}, "enabled": True},
    ])
    mgr.restart_server.assert_awaited_once_with("github")
    mgr.add_server.assert_not_called()
    mgr.remove_server.assert_not_called()


async def test_apply_config_disabled_server_is_removed(monkeypatch):
    mgr = _make_manager(monkeypatch)
    from breadmind.mcp.server_manager import MCPServerConfig, MCPServerState
    mgr._servers["github"] = MCPServerState(
        name="github",
        config=MCPServerConfig(name="github", command="npx", args=[], env={}, enabled=True),
        process=None,
        tools=[],
    )
    await mgr.apply_config(servers=[
        {"name": "github", "command": "npx", "args": [], "env": {}, "enabled": False},
    ])
    mgr.remove_server.assert_awaited_once_with("github")
    mgr.add_server.assert_not_called()


async def test_apply_config_global_config_stores_value(monkeypatch):
    mgr = _make_manager(monkeypatch)
    await mgr.apply_config(mcp_cfg={"auto_discover": True})
    assert mgr._global_config == {"auto_discover": True}
```

**NOTE:** The `MCPServerConfig` and `MCPServerState` names here are guesses based on the report. Read `src/breadmind/mcp/server_manager.py` FIRST to confirm the real class names and constructor signatures. If they differ, adapt the test to use the real types.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mcp/test_server_manager_apply_config.py -v`
Expected: FAIL with `AttributeError: 'MCPServerManager' object has no attribute 'apply_config'`.

- [ ] **Step 3: Implement `apply_config`**

In `src/breadmind/mcp/server_manager.py`, add after the existing `restart_server` method:

```python
    async def apply_config(
        self,
        *,
        mcp_cfg: dict | None = None,
        servers: list[dict] | None = None,
    ) -> None:
        """Reconcile running MCP servers against new settings.

        ``servers`` is the new ``mcp_servers`` list from the settings store.
        Each entry is a dict with ``name``, ``command``, ``args``, ``env``,
        ``enabled``. This method:
          * removes servers that are no longer present or are now disabled,
          * adds servers that appear for the first time (and are enabled),
          * restarts servers whose command/args/env changed.

        ``mcp_cfg`` is the global ``mcp`` setting dict (e.g. ``auto_discover``).
        It is stored on the instance so the manager can consult it later; this
        method does not otherwise act on it because dynamic auto-discover is
        out of scope for the current refactor.
        """
        if mcp_cfg is not None:
            self._global_config = dict(mcp_cfg)

        if servers is None:
            return

        new_by_name = {
            s["name"]: s for s in servers if isinstance(s, dict) and s.get("name")
        }

        # Remove servers that disappeared or are now disabled.
        for existing_name in list(self._servers.keys()):
            new_entry = new_by_name.get(existing_name)
            if new_entry is None or not new_entry.get("enabled", True):
                await self.remove_server(existing_name)

        # Add new enabled servers and restart changed ones.
        for name, entry in new_by_name.items():
            if not entry.get("enabled", True):
                continue
            new_config = MCPServerConfig(
                name=entry["name"],
                command=entry["command"],
                args=list(entry.get("args", [])),
                env=dict(entry.get("env", {})),
                enabled=True,
            )
            existing = self._servers.get(name)
            if existing is None:
                await self.add_server(new_config)
                continue
            current_config = getattr(existing, "config", None)
            if current_config is None:
                await self.add_server(new_config)
                continue
            if (
                current_config.command != new_config.command
                or list(current_config.args) != new_config.args
                or dict(current_config.env) != new_config.env
            ):
                # Store the new config so the restart path uses it, then
                # restart the running server.
                existing.config = new_config
                await self.restart_server(name)
```

Also add `self._global_config: dict = {}` to `__init__`.

**IMPORTANT:** Inspect the real `MCPServerConfig` / `MCPServerState` signatures before pasting. If fields differ (e.g. `args_list` instead of `args`), use the real names. Do NOT invent new fields.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/mcp/test_server_manager_apply_config.py -v`
Expected: 5 passed.

- [ ] **Step 5: Update the web reloader to call `apply_config` directly**

In `src/breadmind/web/routes/ui.py`, find the Task 13 MCP block (look for `_reload_mcp_global` / `_reload_mcp_servers`). Simplify the fallback now that `apply_config` always exists:

```python
        mcp_manager_obj = getattr(app_state, "_mcp_manager", None)
        if mcp_manager_obj is not None:
            async def _reload_mcp_global(ctx):
                try:
                    await mcp_manager_obj.apply_config(mcp_cfg=ctx["new"])
                except Exception as exc:
                    logger.warning("mcp hot-reload failed: %s", exc)

            async def _reload_mcp_servers(ctx):
                try:
                    await mcp_manager_obj.apply_config(servers=ctx["new"])
                except Exception as exc:
                    logger.warning("mcp_servers hot-reload failed: %s", exc)

            reload_registry.register("mcp", _reload_mcp_global)
            reload_registry.register("mcp_servers", _reload_mcp_servers)
```

The `getattr(..., "apply_config", None)` + `flow_bus.async_emit("mcp_server_reload", ...)` legacy fallback is gone.

- [ ] **Step 6: Run the full relevant suite**

Run: `python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py tests/mcp/ -q`
Expected: 944 + 5 new = 949 passed.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/mcp/server_manager.py src/breadmind/web/routes/ui.py tests/mcp/test_server_manager_apply_config.py
git commit -m "feat(mcp): add MCPServerManager.apply_config for hot-reload"
```

---

## Task 5: `PluginManager.apply_markets` — close the skill-markets hole

**Problem:** The plugin manager has no `apply_markets` method, so the `skill_markets` reloader falls back to a debug log and no-op. Full skill-market sync (downloading, installing, removing marketplace plugins) is a much larger feature that is out of scope for this cleanup plan. The minimal honest fix is to add an `apply_markets` method that records the new marketplace configuration on an instance attribute and logs an info-level "change will apply on restart" message, so the reloader chain is wired to a real method and the future "full sync" feature has a clear insertion point.

**Files:**
- Modify: `src/breadmind/plugins/manager.py`
- Modify: `src/breadmind/web/routes/ui.py`
- Test: `tests/plugins/test_manager_apply_markets.py`

- [ ] **Step 1: Write the failing test**

Create `tests/plugins/test_manager_apply_markets.py`:

```python
import logging

from breadmind.plugins.manager import PluginManager


def _make_manager(tmp_path):
    return PluginManager(plugins_dir=tmp_path)


async def test_apply_markets_stores_new_config(tmp_path):
    mgr = _make_manager(tmp_path)
    markets = [
        {"name": "official", "url": "https://plugins.example.com", "enabled": True},
        {"name": "internal", "url": "https://int.example.com", "enabled": False},
    ]
    await mgr.apply_markets(markets)
    assert mgr.get_markets_config() == markets


async def test_apply_markets_logs_restart_hint(tmp_path, caplog):
    mgr = _make_manager(tmp_path)
    with caplog.at_level(logging.INFO, logger="breadmind.plugins.manager"):
        await mgr.apply_markets([{"name": "official", "url": "x", "enabled": True}])
    messages = [rec.message for rec in caplog.records]
    assert any("restart" in m.lower() or "markets updated" in m.lower() for m in messages)


async def test_apply_markets_empty_list_clears_config(tmp_path):
    mgr = _make_manager(tmp_path)
    await mgr.apply_markets([{"name": "a", "url": "x", "enabled": True}])
    await mgr.apply_markets([])
    assert mgr.get_markets_config() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/plugins/test_manager_apply_markets.py -v`
Expected: FAIL with `AttributeError: 'PluginManager' object has no attribute 'apply_markets'`.

- [ ] **Step 3: Implement `apply_markets` and `get_markets_config`**

In `src/breadmind/plugins/manager.py`, inside `PluginManager.__init__` add:

```python
        self._markets_config: list[dict] = []
```

Then add two methods to the class:

```python
    async def apply_markets(self, markets: list[dict] | None) -> None:
        """Record the new skill-market configuration.

        Full marketplace sync (downloading/installing/removing plugins from
        markets) is a separate feature — this method only updates the stored
        config so the reloader chain has a real target and logs an info
        message indicating that a process restart is required for the full
        effect.
        """
        self._markets_config = list(markets or [])
        logger.info(
            "plugin markets updated (%d entries); full sync requires restart",
            len(self._markets_config),
        )

    def get_markets_config(self) -> list[dict]:
        """Return the most recently applied markets config (for tests / debug)."""
        return list(self._markets_config)
```

Ensure the file already has `logger = logging.getLogger(__name__)` near the top. If not, add it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/plugins/test_manager_apply_markets.py -v`
Expected: 3 passed.

- [ ] **Step 5: Update the web reloader to call `apply_markets` directly**

In `src/breadmind/web/routes/ui.py`, find the Task 13 skill-markets block and simplify:

```python
        plugin_manager_obj = getattr(app_state, "_plugin_mgr", None)
        if plugin_manager_obj is not None:
            async def _reload_skill_markets(ctx):
                try:
                    await plugin_manager_obj.apply_markets(ctx["new"])
                except Exception as exc:
                    logger.warning("skill_markets hot-reload failed: %s", exc)

            reload_registry.register("skill_markets", _reload_skill_markets)
```

The `getattr(..., "apply_markets", None)` + debug-log fallback is gone.

- [ ] **Step 6: Run the full relevant suite**

Run: `python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py tests/plugins/ -q`
Expected: 949 + 3 new = 952 passed.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/plugins/manager.py src/breadmind/web/routes/ui.py tests/plugins/test_manager_apply_markets.py
git commit -m "feat(plugins): add PluginManager.apply_markets for hot-reload"
```

---

## Task 6: `MonitoringEngine.apply` — delegate to existing update methods

**Problem:** The monitoring reloader uses `getattr(monitoring_obj, "apply", None)` + debug fallback. `MonitoringEngine` already has `update_loop_protector_config(cooldown_minutes, max_auto_actions)`, `update_rule_interval(rule_name, interval_seconds)`, `enable_rule(rule_name)`, and `disable_rule(rule_name)` — we just need a thin `apply(...)` dispatcher that routes each settings key to the right update method.

`monitoring_config` carries rule definitions; `loop_protector` carries cooldown/max-auto-actions; `scheduler_cron` and `webhook_endpoints` don't have real wiring yet and stay as debug-logged no-ops.

**Files:**
- Modify: `src/breadmind/monitoring/engine.py`
- Modify: `src/breadmind/web/routes/ui.py`
- Test: `tests/monitoring/test_engine_apply.py`

- [ ] **Step 1: Write the failing test**

Create `tests/monitoring/test_engine_apply.py`:

```python
from unittest.mock import MagicMock

from breadmind.monitoring.engine import MonitoringEngine


def _make_engine():
    engine = MonitoringEngine()
    # Stub the update paths so tests don't depend on the real scheduler.
    engine.update_loop_protector_config = MagicMock()
    engine.update_rule_interval = MagicMock()
    engine.enable_rule = MagicMock()
    engine.disable_rule = MagicMock()
    return engine


async def test_apply_loop_protector_calls_update_loop_protector_config():
    engine = _make_engine()
    await engine.apply(loop_protector={"cooldown_minutes": 7, "max_auto_actions": 5})
    engine.update_loop_protector_config.assert_called_once_with(
        cooldown_minutes=7, max_auto_actions=5,
    )


async def test_apply_monitoring_config_enables_and_updates_intervals():
    engine = _make_engine()
    # Seed fake rules so the method can reason about them.
    rule_a = MagicMock()
    rule_a.name = "a"
    rule_a.enabled = True
    rule_b = MagicMock()
    rule_b.name = "b"
    rule_b.enabled = True
    engine._rules = [rule_a, rule_b]
    await engine.apply(monitoring_config={
        "rules": [
            {"name": "a", "enabled": True, "interval_seconds": 30},
            {"name": "b", "enabled": False},
        ],
    })
    engine.update_rule_interval.assert_called_once_with("a", 30)
    engine.disable_rule.assert_called_once_with("b")


async def test_apply_monitoring_config_with_no_rules_key_is_noop():
    engine = _make_engine()
    engine._rules = []
    await engine.apply(monitoring_config={})
    engine.update_rule_interval.assert_not_called()
    engine.enable_rule.assert_not_called()
    engine.disable_rule.assert_not_called()


async def test_apply_scheduler_cron_is_debug_noop(caplog):
    import logging
    engine = _make_engine()
    with caplog.at_level(logging.DEBUG, logger="breadmind.monitoring.engine"):
        await engine.apply(scheduler_cron={"enabled": True})
    # Should not raise, should not call any update method.
    engine.update_rule_interval.assert_not_called()
    # An info/debug message noting the no-op is expected but not required.


async def test_apply_webhook_endpoints_is_debug_noop():
    engine = _make_engine()
    await engine.apply(webhook_endpoints=[{"url": "https://x"}])
    engine.update_rule_interval.assert_not_called()


async def test_apply_all_four_fields_at_once():
    engine = _make_engine()
    rule_a = MagicMock()
    rule_a.name = "a"
    engine._rules = [rule_a]
    await engine.apply(
        monitoring_config={"rules": [{"name": "a", "enabled": True, "interval_seconds": 10}]},
        loop_protector={"cooldown_minutes": 3, "max_auto_actions": 2},
        scheduler_cron={"enabled": False},
        webhook_endpoints=[],
    )
    engine.update_loop_protector_config.assert_called_once()
    engine.update_rule_interval.assert_called_once_with("a", 10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/monitoring/test_engine_apply.py -v`
Expected: FAIL with `AttributeError: 'MonitoringEngine' object has no attribute 'apply'`.

- [ ] **Step 3: Implement `apply`**

In `src/breadmind/monitoring/engine.py`, add near the existing `update_loop_protector_config` method:

```python
    async def apply(
        self,
        *,
        monitoring_config: dict | None = None,
        loop_protector: dict | None = None,
        scheduler_cron: dict | None = None,
        webhook_endpoints: list | None = None,
    ) -> None:
        """Apply hot-reload updates from the settings pipeline.

        Each kwarg corresponds to a runtime settings key. ``None`` means
        "no change on this axis." Fields without a real runtime path
        (``scheduler_cron``, ``webhook_endpoints``) are accepted and
        debug-logged so the reloader chain has a single target; full
        scheduler/webhook runtime integration is out of scope here.
        """
        if loop_protector is not None:
            try:
                self.update_loop_protector_config(
                    cooldown_minutes=loop_protector.get("cooldown_minutes"),
                    max_auto_actions=loop_protector.get("max_auto_actions"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("loop_protector apply failed: %s", exc)

        if monitoring_config is not None:
            rules_cfg = monitoring_config.get("rules") or []
            cfg_by_name = {
                r.get("name"): r for r in rules_cfg if isinstance(r, dict)
            }
            for rule in self._rules:
                cfg = cfg_by_name.get(rule.name)
                if cfg is None:
                    continue
                if cfg.get("enabled", True):
                    if not rule.enabled:
                        self.enable_rule(rule.name)
                    interval = cfg.get("interval_seconds")
                    if interval is not None:
                        self.update_rule_interval(rule.name, interval)
                else:
                    self.disable_rule(rule.name)

        if scheduler_cron is not None:
            logger.debug(
                "monitoring.apply: scheduler_cron updated but no runtime "
                "scheduler is wired yet",
            )
        if webhook_endpoints is not None:
            logger.debug(
                "monitoring.apply: webhook_endpoints updated but no runtime "
                "dispatcher is wired yet",
            )
```

Ensure the module has `logger = logging.getLogger(__name__)` near the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/monitoring/test_engine_apply.py -v`
Expected: 6 passed.

- [ ] **Step 5: Update the web reloader to call `apply` directly**

In `src/breadmind/web/routes/ui.py`, find the Task 13 monitoring block and simplify:

```python
        monitoring_obj = getattr(app_state, "_monitoring_engine", None)
        if monitoring_obj is not None:
            def _monitoring_setter(kw: str):
                async def _fn(ctx):
                    try:
                        await monitoring_obj.apply(**{kw: ctx["new"]})
                    except Exception as exc:
                        logger.warning("monitoring reload %s failed: %s", kw, exc)
                return _fn

            reload_registry.register("monitoring_config", _monitoring_setter("monitoring_config"))
            reload_registry.register("loop_protector", _monitoring_setter("loop_protector"))
            reload_registry.register("scheduler_cron", _monitoring_setter("scheduler_cron"))
            reload_registry.register("webhook_endpoints", _monitoring_setter("webhook_endpoints"))
```

The getattr fallback is gone.

- [ ] **Step 6: Run the full relevant suite**

Run: `python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py tests/monitoring/ -q`
Expected: 952 + 6 new = 958 passed.

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/monitoring/engine.py src/breadmind/web/routes/ui.py tests/monitoring/test_engine_apply.py
git commit -m "feat(monitoring): add MonitoringEngine.apply for hot-reload"
```

---

## Task 7: `PromptContext.custom_prompts` field

**Problem:** Task 10 of the parent plan wired a `custom_prompts` reloader that stashes the value on `CoreAgent._custom_prompts` but logs a debug "not implemented" message because `PromptContext` has no `custom_prompts` field and no template fragment consumes it. The setting is live but has no effect.

**Solution:** Add `custom_prompts: dict[str, str] | None = None` to `PromptContext`, accept it in `PromptBuilder.build(...)`, and merge it into the template variable dict with a prefix so custom prompts appear as `{{ custom_prompt_<name> }}` in any template that wants to render them. No existing template is modified (that would be a behavior change); this task only makes the data *available* to templates.

Also update `CoreAgent.reload_prompt_components(custom_prompts=...)` to pass the value into the next `_rebuild_system_prompt()` call instead of just stashing it.

**Files:**
- Modify: `src/breadmind/prompts/builder.py`
- Modify: `src/breadmind/core/agent.py`
- Test: `tests/prompts/test_prompt_builder_custom_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/prompts/test_prompt_builder_custom_prompts.py`:

```python
import pytest

from breadmind.prompts.builder import PromptBuilder, PromptContext


def test_prompt_context_has_custom_prompts_field():
    ctx = PromptContext()
    assert hasattr(ctx, "custom_prompts")
    assert ctx.custom_prompts is None


def test_prompt_builder_accepts_custom_prompts_kwarg():
    builder = PromptBuilder()
    # Should not raise TypeError.
    out = builder.build(
        provider="claude",
        persona="professional",
        custom_prompts={"greeting": "Welcome!", "disclaimer": "Be careful."},
    )
    # The returned system prompt is a non-empty string (we don't assert the
    # custom prompts appear unless a template uses them — that's out of
    # scope for this task).
    assert isinstance(out, str)
    assert len(out) > 0


def test_prompt_builder_custom_prompts_flow_into_variables():
    """The builder should expose custom prompts as `custom_prompt_<name>` variables.

    This is verified by rendering a minimal template that consumes the
    variable directly — we build a fake PromptBuilder subclass that exposes
    the variable dict.
    """
    class SpyBuilder(PromptBuilder):
        def __init__(self):
            super().__init__()
            self.last_variables: dict = {}

        def _render(self, template_vars):  # hypothetical hook
            self.last_variables = template_vars
            return ""

    # This test is aspirational — it asserts that merging happens BEFORE
    # rendering so any consumer template can pick up the variables. If the
    # real PromptBuilder has no render hook we can monkey-patch, skip this
    # test and only rely on the first two.
    pytest.skip("requires render hook on PromptBuilder; first two tests cover the contract")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/prompts/test_prompt_builder_custom_prompts.py -v`
Expected: first test FAILS with `AttributeError` on `custom_prompts`, second FAILS with `TypeError: build() got an unexpected keyword argument 'custom_prompts'`, third SKIP.

- [ ] **Step 3: Add `custom_prompts` to `PromptContext`**

In `src/breadmind/prompts/builder.py`, add to the `PromptContext` dataclass:

```python
@dataclass
class PromptContext:
    persona_name: str = "BreadMind"
    language: str = "ko"
    specialties: list[str] = field(default_factory=list)
    os_info: str = ""
    current_date: str = ""
    available_tools: list[str] = field(default_factory=list)
    provider_model: str = ""
    custom_instructions: str | None = None
    custom_prompts: dict[str, str] | None = None
```

- [ ] **Step 4: Accept `custom_prompts` in `build()`**

Update `PromptBuilder.build(...)` signature to take a new `custom_prompts` kwarg and merge it into the variable dict:

```python
    def build(
        self,
        provider: str,
        persona: str = "professional",
        role: str | None = None,
        context: PromptContext | None = None,
        token_budget: int | None = None,
        db_overrides: dict | None = None,
        custom_prompts: dict[str, str] | None = None,
    ) -> str:
        # ... existing setup ...

        # After the existing variable dict is built but before render(),
        # merge custom_prompts under a predictable prefix so templates that
        # want them can use {{ custom_prompt_<name> }}.
        if custom_prompts:
            for name, body in custom_prompts.items():
                if isinstance(name, str) and isinstance(body, str):
                    variables[f"custom_prompt_{name}"] = body

        # ... existing render call ...
```

The exact location of `variables = {...}` construction depends on the current body. Read the file and insert the merge block just before `return self._render(...)` or the Jinja2 render call. Do NOT modify existing variable keys.

Also: if `context.custom_prompts` is set but the kwarg is not, treat the context field as the source:

```python
        if custom_prompts is None and context is not None:
            custom_prompts = context.custom_prompts
```

- [ ] **Step 5: Update `CoreAgent.reload_prompt_components` to route custom_prompts through rebuild**

In `src/breadmind/core/agent.py`, find `reload_prompt_components`. Update the `custom_prompts` branch so it doesn't just stash the value:

```python
    def reload_prompt_components(
        self,
        *,
        persona: str | dict | None = None,
        custom_prompts: dict | None = None,
        custom_instructions: str | None = None,
    ) -> None:
        if persona is not None:
            if isinstance(persona, dict):
                self.set_persona(persona)
            else:
                self.set_persona_name(persona)
        if custom_instructions is not None:
            self.set_custom_instructions(custom_instructions)
        if custom_prompts is not None:
            self._custom_prompts = custom_prompts
            self._rebuild_system_prompt()
```

And ensure `_rebuild_system_prompt` passes `custom_prompts=self._custom_prompts` to the builder:

```python
    def _rebuild_system_prompt(self) -> None:
        if self._prompt_builder is None:
            return
        self._system_prompt = self._prompt_builder.build(
            provider=self._provider_name,
            persona=self._persona,
            role=self._role,
            context=self._prompt_context,
            custom_prompts=getattr(self, "_custom_prompts", None),
        )
```

Adapt the existing `_rebuild_system_prompt` to the real signature — if it doesn't currently exist as a named method, the change is to wherever the builder's `build()` is called from `set_persona`/`set_custom_instructions`.

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/prompts/test_prompt_builder_custom_prompts.py -v`
Expected: 2 passed, 1 skipped.

- [ ] **Step 7: Run the full relevant suite**

Run: `python -m pytest tests/sdui/ tests/settings/ tests/tools/ tests/web/test_ws_ui.py tests/prompts/ -q`
Expected: 958 + 2 new = 960 passed.

- [ ] **Step 8: Commit**

```bash
git add src/breadmind/prompts/builder.py src/breadmind/core/agent.py tests/prompts/test_prompt_builder_custom_prompts.py
git commit -m "feat(prompts): add custom_prompts field + builder kwarg for hot-reload"
```

---

## Self-Review Checklist

Before execution, the implementer should confirm:

1. **Task 1** completely removes `_rewrite_last_audit`. Grep the repo after Task 1 — `_rewrite_last_audit` must return zero hits.
2. **Task 2** does NOT delete `_prepare_*_item` helpers (they are the active translator path) or `_audit_summary_*` helpers (they are used by `_record_audit` compat shim). Only the dead-code helpers identified by the review go.
3. **Task 3**'s extracted `build_settings_pipeline` leaves the LLM/persona/safety/MCP/plugin/monitoring reloaders in `_ensure_projector` — the extraction is only for the generic pipeline construction, not the per-component subscribers. A future cleanup pass can decompose those.
4. **Task 4**'s `apply_config` uses the real `MCPServerConfig`/`MCPServerState` classes and attribute names from `src/breadmind/mcp/server_manager.py`. Test file must be adapted if the guessed types differ.
5. **Task 5** intentionally does NOT implement full marketplace sync. It only records the new config and logs a restart hint. Full sync is a separate feature.
6. **Task 6**'s `monitoring_config` handling only understands rules by name (enable/disable/update interval). Creating new rules from settings is out of scope because the rule schema (`condition_fn`, etc.) is code-only. A reloader cannot reconstruct a callable from JSON.
7. **Task 7** does not modify any existing Jinja2 template. It only adds the `custom_prompts` data to the variable dict so future templates can opt in.

## Out of Scope for this Plan

- Full marketplace sync for `skill_markets`.
- Dynamic scheduler/webhook runtime for `scheduler_cron` / `webhook_endpoints`.
- Creating new `MonitoringRule` instances from settings (requires a factory pattern that doesn't exist yet).
- `mcp_cfg.auto_discover` runtime toggling.
- Template modifications to consume `custom_prompts`.
- Further decomposition of `_ensure_projector` beyond the generic pipeline extraction.
