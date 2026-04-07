"""Web application context container.

Centralizes all WebApp dependencies into a single dataclass, eliminating the
22+ parameter constructor anti-pattern and enabling easier testing via
dependency injection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from breadmind.core.bootstrap.components import AppComponents


@dataclass
class AppContext:
    """Container for all web application dependencies.

    Each field corresponds to a former ``WebApp.__init__`` keyword argument.
    All fields default to ``None`` so partial construction (e.g. in tests)
    is straightforward.
    """

    # Core
    message_handler: Callable | None = None
    config: Any = None
    agent: Any = None

    # Tools & Safety
    tool_registry: Any = None
    safety_config: Any = None
    safety_guard: Any = None
    search_engine: Any = None
    skill_store: Any = None
    performance_tracker: Any = None

    # MCP
    mcp_manager: Any = None
    mcp_store: Any = None

    # Infrastructure
    monitoring_engine: Any = None
    audit_logger: Any = None
    metrics_collector: Any = None
    database: Any = None

    # Memory
    working_memory: Any = None
    embedding_service: Any = None

    # Messaging & Routing
    message_router: Any = None
    webhook_manager: Any = None
    webhook_automation_store: Any = None
    webhook_rule_engine: Any = None
    webhook_pipeline_executor: Any = None
    messenger_security: Any = None
    lifecycle_manager: Any = None
    orchestrator: Any = None

    # Auth
    auth: Any = None
    token_manager: Any = None

    # Scheduling & Jobs
    scheduler: Any = None
    subagent_manager: Any = None
    bg_job_manager: Any = None

    # Container & Swarm
    container_executor: Any = None
    swarm_manager: Any = None
    commander: Any = None

    # Plugins
    plugin_mgr: Any = None

    @classmethod
    def from_components(cls, components: AppComponents) -> AppContext:
        """Create an AppContext from a bootstrap AppComponents instance.

        Maps the hierarchical AppComponents fields to the flat AppContext
        fields that the web layer expects.
        """
        # Messenger components may live in the service container
        _container = getattr(components, "container", None)

        def _resolve(name: str) -> Any:
            if _container is not None:
                try:
                    return _container.resolve(name)
                except Exception:
                    return None
            return None

        return cls(
            config=components.config,
            agent=components.agent,
            tool_registry=components.registry,
            safety_config=components.safety_cfg,
            safety_guard=components.guard,
            search_engine=components.search_engine,
            skill_store=components.skill_store,
            performance_tracker=components.performance_tracker,
            mcp_manager=components.mcp_manager,
            mcp_store=components.mcp_store,
            monitoring_engine=components.monitoring_engine,
            audit_logger=components.audit_logger,
            metrics_collector=components.metrics_collector,
            database=components.db,
            working_memory=components.working_memory,
            embedding_service=_resolve("embedding_service"),
            swarm_manager=components.swarm_manager,
            plugin_mgr=components.plugin_mgr,
            bg_job_manager=components.bg_job_manager,
        )
