"""Assemble the SettingsService + reload pipeline for the web app.

Extracted from ``_ensure_projector`` so its 300+ lines of wiring live in a
dedicated module that can be unit-tested without a full web app fixture.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from breadmind.core.events import EventBus
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
    settings_event_bus: EventBus


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

    # Settings changes use their own lightweight EventBus, NOT the
    # FlowEventBus. The two buses have incompatible APIs — FlowEventBus
    # publishes typed FlowEvent objects, while SettingsService.emit needs
    # a (event_name, dict) publish channel. Wiring settings writes through
    # flow_bus raised AttributeError: 'FlowEventBus' has no 'async_emit'.
    settings_event_bus = EventBus()

    async def _placeholder_audit(**_kwargs):
        return None

    settings_service = SettingsService(
        store=settings_store,
        vault=credential_vault,
        audit_sink=_placeholder_audit,
        reload_registry=reload_registry,
        event_bus=settings_event_bus,
        approval_queue=approval_queue,
        rate_limiter=rate_limiter,
    )

    action_handler = ActionHandler(
        bus=flow_bus,
        message_handler=message_handler,
        working_memory=working_memory,
        settings_store=settings_store,
        credential_vault=credential_vault,
        event_bus=settings_event_bus,
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
        settings_event_bus=settings_event_bus,
    )
