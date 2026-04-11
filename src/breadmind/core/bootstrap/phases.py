"""Individual bootstrap phases, each initializing one subsystem.

Each function receives an ``AppComponents`` instance and mutates it
in-place, keeping all try/except blocks and logging exactly as they
appeared in the original monolithic ``bootstrap_all()``.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from breadmind.core.bootstrap.components import AppComponents

logger = logging.getLogger(__name__)


# ── Phase 1: Database ───────────────────────────────────────────────────


async def init_phase_database(
    components: AppComponents,
    config: Any,
    config_dir: str,
) -> None:
    """Phase 1: Initialize database connection."""
    try:
        from breadmind.core.bootstrap import init_database

        components.db = await init_database(config, config_dir)
        logger.info("Phase 1 complete: database initialized")
    except Exception as e:
        logger.error("Phase 1 failed (database): %s", e)
        from breadmind.storage.settings_store import FileSettingsStore

        components.db = FileSettingsStore(os.path.join(config_dir, "settings.json"))


# ── Phase 1.5: Credential Vault ─────────────────────────────────────────


async def init_phase_credentials(components: AppComponents) -> None:
    """Phase 1.5: Initialize credential vault."""
    try:
        from breadmind.storage.credential_vault import CredentialVault

        components.credential_vault = CredentialVault(components.db)
        await components.credential_vault.migrate_plaintext_credentials()
        logger.info("Phase 1.5 complete: credential vault initialized")
    except Exception as e:
        logger.warning("Credential vault init failed (non-critical): %s", e)


# ── Phase 2: Core services -> ServiceContainer ──────────────────────────


async def init_phase_core_services(
    components: AppComponents,
    config: Any,
    provider: Any,
    safety_cfg: dict,
) -> None:
    """Phase 2: Initialize core services and populate ServiceContainer."""
    try:
        from breadmind.core.bootstrap import init_core_services

        services = await init_core_services(
            config,
            components.db,
            provider,
            safety_cfg,
            vault=components.credential_vault,
        )
        container = services["container"]
        components.container = container
        components.registry = services["registry"]
        components.guard = services["guard"]
        components.mcp_manager = services["mcp_manager"]
        components.search_engine = services["search_engine"]
        components.performance_tracker = services["performance_tracker"]
        components.skill_store = services["skill_store"]
        components.tool_gap_detector = services["tool_gap_detector"]
        components.working_memory = services["working_memory"]
        components.episodic_memory = services["episodic_memory"]
        components.semantic_memory = services["semantic_memory"]
        components.smart_retriever = services["smart_retriever"]
        components.profiler = services.get("profiler")
        components.context_builder = services.get("context_builder")
        components.mcp_store = services.get("mcp_store")
        components.adapter_registry = services.get("adapter_registry")
        components.oauth_manager = services.get("oauth_manager")
        logger.info("Phase 2 complete: core services initialized")
    except Exception as e:
        logger.error("Phase 2 failed (core services): %s", e)


# ── Phase 4: Plugin loading ─────────────────────────────────────────────


async def init_phase_plugins(components: AppComponents) -> None:
    """Phase 4: Load builtin and user plugins via PluginManager."""
    if components.container is not None:
        try:
            from breadmind.core.bootstrap import init_plugins

            components.plugin_mgr = await init_plugins(components.container)
            logger.info(
                "Phase 4 complete: plugins loaded (%d)",
                len(components.plugin_mgr.loaded_plugins),
            )
        except Exception as e:
            logger.error("Phase 4 failed (plugins): %s", e)


# ── Phase 5: Agent ──────────────────────────────────────────────────────


async def init_phase_agent(
    components: AppComponents,
    config: Any,
    provider: Any,
    safety_cfg: dict,
) -> None:
    """Phase 5: Initialize CoreAgent with BehaviorTracker."""
    try:
        from breadmind.core.bootstrap import init_agent

        (
            components.agent,
            components.behavior_tracker,
            components.audit_logger,
            components.metrics_collector,
        ) = await init_agent(
            config,
            provider,
            components.registry,
            components.guard,
            components.db,
            {
                "working_memory": components.working_memory,
                "episodic_memory": components.episodic_memory,
                "semantic_memory": components.semantic_memory,
                "smart_retriever": components.smart_retriever,
                "tool_gap_detector": components.tool_gap_detector,
                "context_builder": components.context_builder,
                "profiler": components.profiler,
            },
            orchestrator=(
                components.container.get("orchestrator")
                if components.container
                else None
            ),
        )
        logger.info("Phase 5 complete: agent initialized")
    except Exception as e:
        logger.error("Phase 5 failed (agent): %s", e)


# ── Phase 6: Messenger (optional) ───────────────────────────────────────


async def init_phase_messengers(
    components: AppComponents,
    message_router: Any,
    event_callback: Any = None,
) -> None:
    """Phase 6: Initialize messenger auto-connect, lifecycle, and security."""
    if message_router is not None:
        try:
            from breadmind.core.bootstrap import init_messenger

            messenger_result = await init_messenger(
                components.db,
                message_router,
                event_callback,
                vault=components.credential_vault,
            )
            # Register messenger connection orchestrator in container for messenger plugin
            if components.container and messenger_result.get("orchestrator"):
                components.container.register(
                    "connection_orchestrator",
                    messenger_result["orchestrator"],
                )
            logger.info("Phase 6 complete: messenger initialized")
        except Exception as e:
            logger.error("Phase 6 failed (messenger): %s", e)


# ── Phase 7: Background Jobs ────────────────────────────────────────────


async def init_phase_background(
    components: AppComponents,
    config: Any,
) -> None:
    """Phase 7: Initialize background job manager."""
    try:
        from breadmind.storage.bg_jobs_store import BgJobsStore
        from breadmind.tasks.manager import BackgroundJobManager

        if hasattr(components.db, "acquire"):
            store = BgJobsStore(components.db)
            task_cfg = getattr(config, "task", None)
            redis_url = (
                task_cfg.redis_url if task_cfg else "redis://localhost:6379/0"
            )
            max_monitors = (
                task_cfg.max_concurrent_monitors if task_cfg else 10
            )

            mgr = BackgroundJobManager(
                store, redis_url=redis_url, max_monitors=max_monitors,
            )
            await mgr.recover_on_startup()

            retention = task_cfg.completed_retention_days if task_cfg else 30
            await mgr.cleanup_old_jobs(retention)

            # Register in container for background-jobs plugin
            if components.container:
                components.container.register("bg_job_manager", mgr)

            components.bg_job_manager = mgr
            logger.info("Phase 7 complete: background jobs initialized")
        else:
            logger.info("Phase 7 skipped: background jobs require PostgreSQL")
    except Exception as e:
        logger.warning("Phase 7 failed (background jobs): %s", e)


# ── Phase 8: Personal Scheduler ─────────────────────────────────────────


async def init_phase_personal(
    components: AppComponents,
    message_router: Any,
) -> None:
    """Phase 8: Start personal scheduler for proactive notifications."""
    if components.adapter_registry is not None and message_router is not None:
        try:
            from breadmind.personal.proactive import PersonalScheduler

            personal_scheduler = PersonalScheduler(
                components.adapter_registry,
                message_router,
            )
            await personal_scheduler.start()
            components.personal_scheduler = personal_scheduler
            logger.info("PersonalScheduler started")
        except Exception as e:
            logger.warning("PersonalScheduler not started: %s", e)
