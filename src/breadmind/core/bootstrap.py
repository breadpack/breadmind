"""Application bootstrap — initializes all components from config."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AppComponents:
    """Container for all initialized application components."""
    config: Any = None
    db: Any = None
    provider: Any = None
    registry: Any = None
    guard: Any = None
    agent: Any = None
    working_memory: Any = None
    monitoring_engine: Any = None
    mcp_manager: Any = None
    mcp_store: Any = None
    swarm_manager: Any = None
    behavior_tracker: Any = None
    skill_store: Any = None
    performance_tracker: Any = None
    search_engine: Any = None
    context_builder: Any = None
    episodic_memory: Any = None
    semantic_memory: Any = None
    smart_retriever: Any = None
    profiler: Any = None
    safety_cfg: Any = field(default_factory=dict)
    meta_tools: Any = field(default_factory=dict)
    audit_logger: Any = None
    metrics_collector: Any = None
    tool_gap_detector: Any = None


async def init_database(config, config_dir: str):
    """Initialize database or fall back to file-based settings."""
    db = None
    try:
        from breadmind.storage.database import Database
        db_cfg = config.database
        dsn = f"postgresql://{db_cfg.user}:{db_cfg.password}@{db_cfg.host}:{db_cfg.port}/{db_cfg.name}"
        db = Database(dsn)
        await db.connect()
        from breadmind.config import apply_db_settings
        await apply_db_settings(config, db)
        print("  Database connected, settings loaded")
    except Exception as e:
        print(f"  Database not available ({e}), using file-based settings")
        from breadmind.storage.settings_store import FileSettingsStore
        db = FileSettingsStore(os.path.join(config_dir, "settings.json"))
        from breadmind.config import apply_db_settings
        await apply_db_settings(config, db)
        print(f"  Settings: {config_dir}/settings.json")
    return db


async def init_tools(config, safety_cfg):
    """Initialize tool registry, MCP client, and meta tools.

    Returns (registry, guard, mcp_manager, search_engine, meta_tools).
    """
    from breadmind.tools.registry import ToolRegistry
    from breadmind.core.safety import SafetyGuard
    from breadmind.tools.builtin import (
        shell_exec, web_search, file_read, file_write,
        messenger_connect, swarm_role,
    )
    from breadmind.tools.mcp_client import MCPClientManager
    from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig
    from breadmind.tools.meta import create_meta_tools

    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    # Built-in tools
    for t in [shell_exec, web_search, file_read, file_write, messenger_connect, swarm_role]:
        registry.register(t)

    # Browser tools (optional)
    try:
        from breadmind.tools.browser import register_browser_tools
        register_browser_tools(registry)
    except Exception:
        pass

    # MCP
    mcp_manager = MCPClientManager(
        max_restart_attempts=config.mcp.max_restart_attempts,
        call_timeout=config.llm.tool_call_timeout_seconds,
    )

    async def mcp_execute(server_name, tool_name, arguments):
        return await mcp_manager.call_tool(server_name, tool_name, arguments)
    registry._mcp_callback = mcp_execute

    # Connect configured MCP servers
    for name, srv_cfg in config.mcp.servers.items():
        try:
            transport = srv_cfg.get("transport", "stdio")
            if transport == "sse":
                defs = await mcp_manager.connect_sse_server(
                    name, srv_cfg["url"], headers=srv_cfg.get("headers"),
                )
            else:
                defs = await mcp_manager.start_stdio_server(
                    name, srv_cfg["command"], srv_cfg.get("args", []),
                    env=srv_cfg.get("env"),
                )
            for d in defs:
                registry.register_mcp_tool(d, server_name=name, execute_callback=mcp_execute)
            print(f"  Connected MCP server: {name} ({len(defs)} tools)")
        except Exception as e:
            print(f"  Failed to connect MCP server '{name}': {e}")

    # Search engine & meta tools
    search_engine = RegistrySearchEngine([
        RegistryConfig(name=r.name, type=r.type, enabled=r.enabled, url=r.url)
        for r in config.mcp.registries
    ])
    meta_tools = create_meta_tools(mcp_manager, search_engine)
    for func in meta_tools.values():
        registry.register(func)

    return registry, guard, mcp_manager, search_engine, meta_tools


async def init_memory(db, provider, config, registry, mcp_manager, search_engine):
    """Initialize memory layers, SmartRetriever, profiler, and self-expansion components.

    Returns a dict of all memory-related components.
    """
    from breadmind.memory.working import WorkingMemory
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.memory.embedding import EmbeddingService
    from breadmind.core.smart_retriever import SmartRetriever
    from breadmind.core.performance import PerformanceTracker
    from breadmind.core.skill_store import SkillStore
    from breadmind.core.tool_gap import ToolGapDetector
    from breadmind.tools.meta import create_expansion_tools

    # Self-expansion components
    performance_tracker = PerformanceTracker(db=db)
    await performance_tracker.load_from_db()

    skill_store = SkillStore(db=db, tracker=performance_tracker)
    await skill_store.load_from_db()

    tool_gap_detector = ToolGapDetector(
        tool_registry=registry,
        mcp_manager=mcp_manager,
        search_engine=search_engine,
    )

    # Memory layers
    episodic_memory = EpisodicMemory(db=db)
    semantic_memory = SemanticMemory(db=db)
    embedding_service = EmbeddingService()

    smart_retriever = SmartRetriever(
        embedding_service=embedding_service,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        skill_store=skill_store,
        db=db,
    )
    skill_store.set_retriever(smart_retriever)

    # Register expansion meta tools
    expansion_tools = create_expansion_tools(
        skill_store=skill_store,
        tracker=performance_tracker,
    )
    for func in expansion_tools.values():
        registry.register(func)

    # MCP Store
    mcp_store = None
    try:
        from breadmind.mcp.store import MCPStore
        from breadmind.mcp.install_assistant import InstallAssistant
        install_assistant = InstallAssistant(provider=provider)
        mcp_store = MCPStore(
            mcp_manager=mcp_manager,
            registry_search=search_engine,
            install_assistant=install_assistant,
            db=db,
            tool_registry=registry,
        )
        await mcp_store.auto_restore_servers()
        print("  MCP Store: ready")
    except Exception as e:
        print(f"  MCP Store: not available ({e})")

    working_memory = WorkingMemory(db=db)

    # Optional: UserProfiler
    profiler = None
    try:
        from breadmind.memory.profiler import UserProfiler
        profiler = UserProfiler(db=db)
        await profiler.load_from_db()
    except (ImportError, Exception):
        pass

    # Context builder
    context_builder = None
    try:
        from breadmind.memory.context_builder import ContextBuilder
        context_builder = ContextBuilder(
            working_memory=working_memory,
            episodic_memory=episodic_memory,
            semantic_memory=semantic_memory,
            profiler=profiler,
            max_context_tokens=4000,
            skill_store=skill_store,
            smart_retriever=smart_retriever,
        )
    except (ImportError, Exception):
        pass

    return {
        "working_memory": working_memory,
        "episodic_memory": episodic_memory,
        "semantic_memory": semantic_memory,
        "embedding_service": embedding_service,
        "smart_retriever": smart_retriever,
        "performance_tracker": performance_tracker,
        "skill_store": skill_store,
        "tool_gap_detector": tool_gap_detector,
        "context_builder": context_builder,
        "profiler": profiler,
        "mcp_store": mcp_store,
    }


async def init_agent(config, provider, registry, guard, db, memory_components):
    """Initialize CoreAgent with BehaviorTracker.

    Returns (agent, behavior_tracker, audit_logger, metrics_collector).
    """
    from breadmind.core.agent import CoreAgent
    from breadmind.config import build_system_prompt, DEFAULT_PERSONA
    from breadmind.core.behavior_tracker import BehaviorTracker
    from breadmind.tools.meta import create_memory_tools

    # Register memory tools (after profiler init)
    mem_tools = create_memory_tools(
        episodic_memory=memory_components["episodic_memory"],
        profiler=memory_components.get("profiler"),
        smart_retriever=memory_components["smart_retriever"],
    )
    for func in mem_tools.values():
        registry.register(func)

    # Optional components
    audit_logger = None
    try:
        from breadmind.core.audit import AuditLogger
        audit_logger = AuditLogger()
    except (ImportError, Exception):
        pass

    metrics_collector = None
    try:
        from breadmind.core.metrics import MetricsCollector
        metrics_collector = MetricsCollector()
    except (ImportError, Exception):
        pass

    # Wire metrics_collector to registry if supported
    if metrics_collector is not None and hasattr(registry, 'set_metrics_collector'):
        registry.set_metrics_collector(metrics_collector)

    # Load saved behavior prompt
    saved_behavior_prompt = None
    if db is not None:
        try:
            bp_data = await db.get_setting("behavior_prompt")
            if bp_data and "prompt" in bp_data:
                saved = bp_data["prompt"]
                if "Autonomous Problem Solving" in saved:
                    saved_behavior_prompt = saved
                else:
                    logger.info("Discarding saved behavior prompt (missing autonomous solving section)")
        except Exception:
            pass

    system_prompt = build_system_prompt(
        DEFAULT_PERSONA, behavior_prompt=saved_behavior_prompt,
    )

    agent_kwargs = dict(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        system_prompt=system_prompt,
        max_turns=config.llm.tool_call_max_turns,
        working_memory=memory_components["working_memory"],
        tool_gap_detector=memory_components["tool_gap_detector"],
        context_builder=memory_components.get("context_builder"),
        behavior_prompt=saved_behavior_prompt,
    )
    if audit_logger is not None:
        agent_kwargs["audit_logger"] = audit_logger

    agent = CoreAgent(**agent_kwargs)

    # Wire BehaviorTracker
    behavior_tracker = BehaviorTracker(
        provider=provider,
        get_behavior_prompt=agent.get_behavior_prompt,
        set_behavior_prompt=agent.set_behavior_prompt,
        add_notification=agent.add_notification,
        db=db,
    )
    agent.set_behavior_tracker(behavior_tracker)

    return agent, behavior_tracker, audit_logger, metrics_collector
