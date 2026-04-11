"""Hierarchical AppComponents — groups flat fields into logical sub-components.

Every original flat field is accessible via backward-compatible ``@property``
on the top-level ``AppComponents`` so that existing code like
``components.db`` or ``components.agent`` keeps working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from breadmind.core.events import EventBus
from breadmind.plugins.container import ServiceContainer


# ── Sub-component groups ───────────────────────────────────────────────────


@dataclass
class DatabaseComponents:
    """Database and credential storage."""
    db: Any = None
    credential_vault: Any = None


@dataclass
class LLMComponents:
    """LLM provider."""
    provider: Any = None


@dataclass
class MemoryComponents:
    """Memory layers and retrieval."""
    working_memory: Any = None
    episodic_memory: Any = None
    semantic_memory: Any = None
    smart_retriever: Any = None
    profiler: Any = None
    context_builder: Any = None


@dataclass
class ToolComponents:
    """Tool registry, safety, MCP, search, and skills."""
    registry: Any = None
    guard: Any = None
    mcp_manager: Any = None
    mcp_store: Any = None
    search_engine: Any = None
    tool_gap_detector: Any = None
    skill_store: Any = None
    performance_tracker: Any = None
    meta_tools: Any = field(default_factory=dict)


@dataclass
class PluginComponents:
    """Plugin manager and service container."""
    plugin_mgr: Any = None
    container: ServiceContainer | None = None


@dataclass
class MonitoringComponents:
    """Monitoring, auditing, and behavior tracking."""
    monitoring_engine: Any = None
    behavior_tracker: Any = None
    audit_logger: Any = None
    metrics_collector: Any = None


@dataclass
class NetworkComponents:
    """Distributed / swarm networking."""
    swarm_manager: Any = None


@dataclass
class PersonalComponents:
    """Personal assistant adapters and scheduling."""
    adapter_registry: Any = None
    oauth_manager: Any = None
    personal_scheduler: Any = None


# ── Top-level container ────────────────────────────────────────────────────


@dataclass
class AppComponents:
    """Container for all initialized application components.

    Fields are organized into logical sub-groups.  For backward
    compatibility every original flat field name is exposed as a
    ``@property`` that delegates to the appropriate sub-group.
    """

    # Core / uncategorized
    config: Any = None
    safety_cfg: Any = field(default_factory=dict)
    event_bus: EventBus | None = None
    agent: Any = None
    bg_job_manager: Any = None

    # Sub-component groups
    database: DatabaseComponents = field(default_factory=DatabaseComponents)
    llm: LLMComponents = field(default_factory=LLMComponents)
    memory: MemoryComponents = field(default_factory=MemoryComponents)
    tools: ToolComponents = field(default_factory=ToolComponents)
    plugins: PluginComponents = field(default_factory=PluginComponents)
    monitoring: MonitoringComponents = field(default_factory=MonitoringComponents)
    network: NetworkComponents = field(default_factory=NetworkComponents)
    personal: PersonalComponents = field(default_factory=PersonalComponents)

    # ── Backward-compatible properties: Database ───────────────────────

    @property
    def db(self) -> Any:
        return self.database.db

    @db.setter
    def db(self, value: Any) -> None:
        self.database.db = value

    @property
    def credential_vault(self) -> Any:
        return self.database.credential_vault

    @credential_vault.setter
    def credential_vault(self, value: Any) -> None:
        self.database.credential_vault = value

    # ── Backward-compatible properties: LLM ────────────────────────────

    @property
    def provider(self) -> Any:
        return self.llm.provider

    @provider.setter
    def provider(self, value: Any) -> None:
        self.llm.provider = value

    # ── Backward-compatible properties: Memory ─────────────────────────

    @property
    def working_memory(self) -> Any:
        return self.memory.working_memory

    @working_memory.setter
    def working_memory(self, value: Any) -> None:
        self.memory.working_memory = value

    @property
    def episodic_memory(self) -> Any:
        return self.memory.episodic_memory

    @episodic_memory.setter
    def episodic_memory(self, value: Any) -> None:
        self.memory.episodic_memory = value

    @property
    def semantic_memory(self) -> Any:
        return self.memory.semantic_memory

    @semantic_memory.setter
    def semantic_memory(self, value: Any) -> None:
        self.memory.semantic_memory = value

    @property
    def smart_retriever(self) -> Any:
        return self.memory.smart_retriever

    @smart_retriever.setter
    def smart_retriever(self, value: Any) -> None:
        self.memory.smart_retriever = value

    @property
    def profiler(self) -> Any:
        return self.memory.profiler

    @profiler.setter
    def profiler(self, value: Any) -> None:
        self.memory.profiler = value

    @property
    def context_builder(self) -> Any:
        return self.memory.context_builder

    @context_builder.setter
    def context_builder(self, value: Any) -> None:
        self.memory.context_builder = value

    # ── Backward-compatible properties: Tools ──────────────────────────

    @property
    def registry(self) -> Any:
        return self.tools.registry

    @registry.setter
    def registry(self, value: Any) -> None:
        self.tools.registry = value

    @property
    def guard(self) -> Any:
        return self.tools.guard

    @guard.setter
    def guard(self, value: Any) -> None:
        self.tools.guard = value

    @property
    def mcp_manager(self) -> Any:
        return self.tools.mcp_manager

    @mcp_manager.setter
    def mcp_manager(self, value: Any) -> None:
        self.tools.mcp_manager = value

    @property
    def mcp_store(self) -> Any:
        return self.tools.mcp_store

    @mcp_store.setter
    def mcp_store(self, value: Any) -> None:
        self.tools.mcp_store = value

    @property
    def search_engine(self) -> Any:
        return self.tools.search_engine

    @search_engine.setter
    def search_engine(self, value: Any) -> None:
        self.tools.search_engine = value

    @property
    def tool_gap_detector(self) -> Any:
        return self.tools.tool_gap_detector

    @tool_gap_detector.setter
    def tool_gap_detector(self, value: Any) -> None:
        self.tools.tool_gap_detector = value

    @property
    def skill_store(self) -> Any:
        return self.tools.skill_store

    @skill_store.setter
    def skill_store(self, value: Any) -> None:
        self.tools.skill_store = value

    @property
    def performance_tracker(self) -> Any:
        return self.tools.performance_tracker

    @performance_tracker.setter
    def performance_tracker(self, value: Any) -> None:
        self.tools.performance_tracker = value

    @property
    def meta_tools(self) -> Any:
        return self.tools.meta_tools

    @meta_tools.setter
    def meta_tools(self, value: Any) -> None:
        self.tools.meta_tools = value

    # ── Backward-compatible properties: Plugins ────────────────────────

    @property
    def plugin_mgr(self) -> Any:
        return self.plugins.plugin_mgr

    @plugin_mgr.setter
    def plugin_mgr(self, value: Any) -> None:
        self.plugins.plugin_mgr = value

    @property
    def container(self) -> ServiceContainer | None:
        return self.plugins.container

    @container.setter
    def container(self, value: ServiceContainer | None) -> None:
        self.plugins.container = value

    # ── Backward-compatible properties: Monitoring ─────────────────────

    @property
    def monitoring_engine(self) -> Any:
        return self.monitoring.monitoring_engine

    @monitoring_engine.setter
    def monitoring_engine(self, value: Any) -> None:
        self.monitoring.monitoring_engine = value

    @property
    def behavior_tracker(self) -> Any:
        return self.monitoring.behavior_tracker

    @behavior_tracker.setter
    def behavior_tracker(self, value: Any) -> None:
        self.monitoring.behavior_tracker = value

    @property
    def audit_logger(self) -> Any:
        return self.monitoring.audit_logger

    @audit_logger.setter
    def audit_logger(self, value: Any) -> None:
        self.monitoring.audit_logger = value

    @property
    def metrics_collector(self) -> Any:
        return self.monitoring.metrics_collector

    @metrics_collector.setter
    def metrics_collector(self, value: Any) -> None:
        self.monitoring.metrics_collector = value

    # ── Backward-compatible properties: Network ────────────────────────

    @property
    def swarm_manager(self) -> Any:
        return self.network.swarm_manager

    @swarm_manager.setter
    def swarm_manager(self, value: Any) -> None:
        self.network.swarm_manager = value

    # ── Backward-compatible properties: Personal ───────────────────────

    @property
    def adapter_registry(self) -> Any:
        return self.personal.adapter_registry

    @adapter_registry.setter
    def adapter_registry(self, value: Any) -> None:
        self.personal.adapter_registry = value

    @property
    def oauth_manager(self) -> Any:
        return self.personal.oauth_manager

    @oauth_manager.setter
    def oauth_manager(self, value: Any) -> None:
        self.personal.oauth_manager = value

    @property
    def personal_scheduler(self) -> Any:
        return self.personal.personal_scheduler

    @personal_scheduler.setter
    def personal_scheduler(self, value: Any) -> None:
        self.personal.personal_scheduler = value
