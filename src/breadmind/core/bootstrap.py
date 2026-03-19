"""Application bootstrap — initializes all components from config.

Bootstrap initialization dependency graph
==========================================

Phase 1 (no dependencies):
  - database (config, config_dir)

Phase 2 (depends on database):
  - tools          (config, safety_cfg)
  - apply_db_settings is called inside init_database

Phase 3 (depends on database + tools):
  - memory         (db, provider, config, registry, mcp_manager, search_engine)

Phase 4 (depends on database + tools + memory):
  - agent          (config, provider, registry, guard, db, memory_components)

Phase 5 (depends on agent):
  - messenger      (db, message_router, event_callback)

Dependency edges (A -> B means A must run before B):
  database  ->  tools
  database  ->  memory
  tools     ->  memory
  memory    ->  agent
  agent     ->  messenger
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from breadmind.core.events import get_event_bus, EventBus

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
    adapter_registry: Any = None
    oauth_manager: Any = None
    credential_vault: Any = None
    personal_scheduler: Any = None
    bg_job_manager: Any = None
    event_bus: EventBus | None = None


def _detect_package_managers() -> list[str]:
    """Quick detection of available package managers via shutil.which()."""
    import shutil
    candidates = ["apt", "apt-get", "dnf", "yum", "apk", "pacman", "zypper",
                   "snap", "flatpak", "brew", "winget", "choco", "scoop"]
    return [pm for pm in candidates if shutil.which(pm)]


async def init_database(config, config_dir: str):
    """Initialize database or fall back to file-based settings.

    Phase: 1
    Dependencies: none
    Provides: db (Database | FileSettingsStore)
    """
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

    Phase: 2
    Dependencies: config (from load_config)
    Provides: registry (ToolRegistry), guard (SafetyGuard),
              mcp_manager (MCPClientManager), search_engine (RegistrySearchEngine),
              meta_tools (dict)
    Returns: (registry, guard, mcp_manager, search_engine, meta_tools)
    """
    from breadmind.tools.registry import ToolRegistry
    from breadmind.core.safety import SafetyGuard
    from breadmind.tools.builtin import register_builtin_tools
    from breadmind.tools.mcp_client import MCPClientManager
    from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig
    from breadmind.tools.meta import create_meta_tools

    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    # Built-in tools (includes shell_exec, web_search, file_read, file_write,
    # messenger_connect, swarm_role, delegate_tasks, network_scan, router_manage)
    register_builtin_tools(registry)

    # Browser tools (optional)
    try:
        from breadmind.tools.browser import register_browser_tools
        register_browser_tools(registry)
    except Exception:
        pass

    # Code delegate tool (optional — requires coding sub-package)
    try:
        _register_code_delegate(registry, db=None)
    except Exception as e:
        logger.warning("Failed to register code_delegate tool: %s", e)

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


def _register_code_delegate(registry, db) -> None:
    """Register the code_delegate tool into the registry.

    The tool handler returned by create_code_delegate_tool() is a plain async
    function without the @tool decorator, so we attach a synthetic
    _tool_definition before calling registry.register().
    """
    from breadmind.coding.tool import create_code_delegate_tool
    from breadmind.llm.base import ToolDefinition

    tool_def_dict, handler = create_code_delegate_tool(db=db)
    handler._tool_definition = ToolDefinition(
        name=tool_def_dict["name"],
        description=tool_def_dict["description"],
        parameters=tool_def_dict["parameters"],
    )
    registry.register(handler)
    logger.info("Registered code_delegate tool")


async def init_memory(db, provider, config, registry, mcp_manager, search_engine, vault=None):
    """Initialize memory layers, SmartRetriever, profiler, and self-expansion components.

    Phase: 3
    Dependencies: db (Phase 1), registry + mcp_manager + search_engine (Phase 2),
                  provider (from LLM init)
    Provides: working_memory, episodic_memory, semantic_memory, embedding_service,
              smart_retriever, performance_tracker, skill_store, tool_gap_detector,
              context_builder, profiler, mcp_store
    Returns: dict of all memory-related components
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

    # Register OS-specific administration skill (tailored to detected package managers)
    from breadmind.skills.os_skills import register_os_skills
    detected_pkg_managers = _detect_package_managers()
    await register_os_skills(skill_store, package_managers=detected_pkg_managers)

    tool_gap_detector = ToolGapDetector(
        tool_registry=registry,
        mcp_manager=mcp_manager,
        search_engine=search_engine,
    )

    # Memory layers
    episodic_memory = EpisodicMemory(db=db)
    semantic_memory = SemanticMemory(db=db)
    # Initialize embedding service from config
    emb_cfg = config.embedding if hasattr(config, 'embedding') else None
    if emb_cfg:
        # Resolve API key: provider-specific key or generic
        import os as _os
        emb_api_key = ""
        if emb_cfg.provider in ("gemini", "auto"):
            emb_api_key = _os.environ.get("GEMINI_API_KEY", "")
        if not emb_api_key and emb_cfg.provider in ("openai", "auto"):
            emb_api_key = _os.environ.get("OPENAI_API_KEY", "")
        if not emb_api_key:
            emb_api_key = _os.environ.get("GEMINI_API_KEY", "") or _os.environ.get("OPENAI_API_KEY", "")
        embedding_service = EmbeddingService(
            provider=emb_cfg.provider,
            api_key=emb_api_key,
            model_name=emb_cfg.model_name,
            ollama_base_url=emb_cfg.ollama_base_url,
        )
        embedding_service._max_cache = emb_cfg.cache_size
    else:
        embedding_service = EmbeddingService()

    # Sync pgvector column dimensions with resolved embedding model
    if embedding_service.is_available() and hasattr(db, 'setup_pgvector'):
        await db.setup_pgvector(embedding_service.dimensions)

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

    # --- Personal assistant adapter registry ---
    adapter_registry = None
    oauth_manager = None
    try:
        from breadmind.personal.adapters.base import AdapterRegistry
        from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
        from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
        from breadmind.personal.context_provider import PersonalContextProvider

        adapter_registry = AdapterRegistry()
        if db:
            adapter_registry.register(BuiltinTaskAdapter(db))
            adapter_registry.register(BuiltinEventAdapter(db))

        # Register personal context provider
        if context_builder:
            context_builder.register_provider(PersonalContextProvider(adapter_registry))

        # Register personal assistant tools
        from breadmind.personal.tools import register_personal_tools
        if registry:
            register_personal_tools(registry, adapter_registry, user_id="default")

        # --- Phase 2: OAuth Manager ---
        from breadmind.personal.oauth import OAuthManager
        oauth_manager = OAuthManager(db, vault=vault)

        # --- Phase 2-3: Google adapters (require OAuth) ---
        # These are registered but only functional after OAuth authentication
        from breadmind.personal.adapters.google_calendar import GoogleCalendarAdapter
        from breadmind.personal.adapters.google_drive import GoogleDriveAdapter
        from breadmind.personal.adapters.google_contacts import GoogleContactsAdapter

        adapter_registry.register(GoogleCalendarAdapter(oauth_manager))
        adapter_registry.register(GoogleDriveAdapter(oauth_manager))
        adapter_registry.register(GoogleContactsAdapter(oauth_manager))

        # --- Phase 3b: Third-party adapters (require API tokens) ---
        # These are registered but only functional after authenticate() is called
        from breadmind.personal.adapters.notion import NotionAdapter
        from breadmind.personal.adapters.jira import JiraAdapter
        from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter

        adapter_registry.register(NotionAdapter())
        adapter_registry.register(JiraAdapter())
        adapter_registry.register(GitHubIssuesAdapter())

        print("  Personal assistant: ready")
    except Exception as e:
        print(f"  Personal assistant: not available ({e})")

    # Phase 4 messenger gateways available:
    # - teams_gw.TeamsGateway (app_id, app_password)
    # - line_gw.LINEGateway (channel_token, channel_secret)
    # - matrix_gw.MatrixGateway (homeserver, access_token, user_id)
    # These are started by GatewayLifecycleManager when configured via CLI/web.

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
        "adapter_registry": adapter_registry,
        "oauth_manager": oauth_manager,
    }


async def discover_and_install_skills(skill_store, search_engine):
    """Auto-discover skills from marketplace based on detected environment.

    Searches marketplace first, falls back to builtin domain skills.
    Designed to run as a background task after startup.
    """
    from breadmind.skills.auto_discovery import auto_discover_skills, apply_fallback_skills
    from breadmind.skills.domain_skills import detect_domains

    detected = detect_domains()
    detected_tool_names = []
    for d in detected:
        detected_tool_names.extend(d.detected_tools)

    if not detected_tool_names:
        return

    # Try marketplace first
    result = await auto_discover_skills(
        detected_tools=detected_tool_names,
        search_engine=search_engine,
        skill_store=skill_store,
        max_per_domain=1,
        timeout=30,
    )

    if result.installed > 0:
        logger.info(
            "Skill auto-discovery: %d searched, %d installed, %d failed",
            result.searched, result.installed, result.failed,
        )

    # Apply builtin fallbacks for domains without marketplace skills
    await apply_fallback_skills(detected_tool_names, skill_store)

    # Persist to DB
    try:
        await skill_store.flush_to_db()
    except Exception:
        pass


async def init_agent(config, provider, registry, guard, db, memory_components):
    """Initialize CoreAgent with BehaviorTracker.

    Phase: 4
    Dependencies: db (Phase 1), registry + guard (Phase 2),
                  memory_components (Phase 3), provider + config
    Provides: agent (CoreAgent), behavior_tracker (BehaviorTracker),
              audit_logger (AuditLogger | None), metrics_collector (MetricsCollector | None)
    Returns: (agent, behavior_tracker, audit_logger, metrics_collector)
    """
    from breadmind.core.agent import CoreAgent
    from breadmind.config import DEFAULT_PERSONA
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

    # Initialize PromptBuilder
    from breadmind.prompts.builder import PromptBuilder, PromptContext
    from pathlib import Path
    import platform as _plat
    from datetime import datetime, timezone

    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"

    def _count_tokens(text: str) -> int:
        return len(text) // 4

    prompt_builder = PromptBuilder(prompts_dir, _count_tokens)

    prompt_context = PromptContext(
        persona_name=DEFAULT_PERSONA.get("name", "BreadMind"),
        language=DEFAULT_PERSONA.get("language", "ko"),
        specialties=DEFAULT_PERSONA.get("specialties", []),
        os_info=f"{_plat.system()} {_plat.release()} ({_plat.machine()})",
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        provider_model=config.llm.default_model,
        custom_instructions=saved_behavior_prompt if saved_behavior_prompt else None,
    )

    provider_name = config.llm.default_provider

    # Build initial system prompt via PromptBuilder
    system_prompt = prompt_builder.build(
        provider=provider_name,
        persona=DEFAULT_PERSONA.get("preset", "professional"),
        context=prompt_context,
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
        profiler=memory_components.get("profiler"),
        prompt_builder=prompt_builder,
    )
    if audit_logger is not None:
        agent_kwargs["audit_logger"] = audit_logger

    agent = CoreAgent(**agent_kwargs)

    # Set PromptBuilder-related attributes
    agent._provider_name = provider_name
    agent._prompt_context = prompt_context
    agent._persona = DEFAULT_PERSONA.get("preset", "professional")

    # Wire BehaviorTracker
    behavior_tracker = BehaviorTracker(
        provider=provider,
        get_behavior_prompt=agent.get_behavior_prompt,
        set_behavior_prompt=agent.set_behavior_prompt,
        add_notification=agent.add_notification,
        db=db,
    )
    agent.set_behavior_tracker(behavior_tracker)

    # Environment scan — runs on first startup or if no scan exists
    try:
        last_scan = await db.get_setting("last_env_scan") if db else None
        if last_scan is None:
            from breadmind.core.env_scanner import scan_environment, store_scan_in_memory
            logger.info("First run detected — scanning environment...")
            scan = await scan_environment()
            await store_scan_in_memory(
                scan,
                episodic_memory=memory_components["episodic_memory"],
                semantic_memory=memory_components["semantic_memory"],
                db=db,
            )
            print(f"  Environment scan: {len(scan.installed_tools)} tools, "
                  f"{len(scan.disks)} disks, {len(scan.ip_addresses)} IPs")
    except Exception as e:
        logger.warning("Environment scan failed: %s", e)

    return agent, behavior_tracker, audit_logger, metrics_collector


async def init_messenger(db, message_router, event_callback=None, vault=None):
    """Initialize messenger auto-connect, lifecycle, and security components.

    Phase: 5
    Dependencies: db (Phase 1), message_router (from agent/Phase 4)
    Provides: security (MessengerSecurityManager), lifecycle (GatewayLifecycleManager),
              orchestrator (ConnectionOrchestrator)
    Returns: dict with security, lifecycle, orchestrator
    """
    from breadmind.messenger.security import MessengerSecurityManager
    from breadmind.messenger.lifecycle import GatewayLifecycleManager
    from breadmind.messenger.auto_connect.orchestrator import ConnectionOrchestrator

    security = MessengerSecurityManager(db, vault=vault)
    await security.load_token_timestamps()

    lifecycle = GatewayLifecycleManager(
        message_router=message_router,
        db=db,
        event_callback=event_callback,
    )

    orchestrator = ConnectionOrchestrator(
        security_manager=security,
        lifecycle_manager=lifecycle,
        db=db,
    )

    # 설정된 게이트웨이 자동 시작
    results = await lifecycle.auto_start_all()
    started = [p for p, ok in results.items() if ok]
    if started:
        logger.info("Auto-started messengers: %s", started)

    return {
        "security": security,
        "lifecycle": lifecycle,
        "orchestrator": orchestrator,
    }


async def bootstrap_all(
    config,
    config_dir: str,
    safety_cfg: dict,
    provider,
    message_router=None,
    event_callback=None,
) -> AppComponents:
    """Run all initialization phases in dependency order.

    This is a convenience entry point that calls each init_* function
    following the DAG order declared at the top of this module.
    Phases that fail are logged and degraded gracefully where possible.

    Phase execution order:
      1. database   (no deps)
      2. tools      (needs config)
      3. memory     (needs db, tools, provider)
      4. agent      (needs db, tools, memory, provider)
      5. messenger  (needs db, agent/message_router)  [optional]

    Args:
        config: Loaded application config object.
        config_dir: Path to the configuration directory.
        safety_cfg: Safety guard configuration dict.
        provider: LLM provider instance.
        message_router: Optional message router for messenger phase.
        event_callback: Optional event callback for messenger phase.

    Returns:
        AppComponents with all initialized (or None for failed) components.
    """
    components = AppComponents(config=config, safety_cfg=safety_cfg)
    components.event_bus = get_event_bus()

    # ── Phase 1: Database ────────────────────────────────────────────
    try:
        components.db = await init_database(config, config_dir)
        logger.info("Phase 1 complete: database initialized")
    except Exception as e:
        logger.error("Phase 1 failed (database): %s", e)
        from breadmind.storage.settings_store import FileSettingsStore
        components.db = FileSettingsStore(os.path.join(config_dir, "settings.json"))

    # ── Phase 1.5: Credential Vault ──────────────────────────────────
    try:
        from breadmind.storage.credential_vault import CredentialVault
        components.credential_vault = CredentialVault(components.db)
        await components.credential_vault.migrate_plaintext_credentials()
        # Inject vault into router manager singleton
        from breadmind.core.router_manager import get_router_manager
        get_router_manager().set_vault(components.credential_vault)
        logger.info("Phase 1.5 complete: credential vault initialized")
    except Exception as e:
        logger.warning("Credential vault init failed (non-critical): %s", e)

    # ── Phase 2: Tools ───────────────────────────────────────────────
    try:
        (
            components.registry,
            components.guard,
            components.mcp_manager,
            components.search_engine,
            components.meta_tools,
        ) = await init_tools(config, safety_cfg)
        logger.info("Phase 2 complete: tools initialized")
    except Exception as e:
        logger.error("Phase 2 failed (tools): %s", e)

    # ── Phase 3: Memory ──────────────────────────────────────────────
    try:
        mem = await init_memory(
            components.db,
            provider,
            config,
            components.registry,
            components.mcp_manager,
            components.search_engine,
            vault=components.credential_vault,
        )
        components.working_memory = mem["working_memory"]
        components.episodic_memory = mem["episodic_memory"]
        components.semantic_memory = mem["semantic_memory"]
        components.smart_retriever = mem["smart_retriever"]
        components.performance_tracker = mem["performance_tracker"]
        components.skill_store = mem["skill_store"]
        components.tool_gap_detector = mem["tool_gap_detector"]
        components.context_builder = mem.get("context_builder")
        components.profiler = mem.get("profiler")
        components.mcp_store = mem.get("mcp_store")
        components.adapter_registry = mem.get("adapter_registry")
        components.oauth_manager = mem.get("oauth_manager")
        logger.info("Phase 3 complete: memory initialized")
    except Exception as e:
        logger.error("Phase 3 failed (memory): %s", e)

    # ── Phase 4: Agent ───────────────────────────────────────────────
    try:
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
        )
        logger.info("Phase 4 complete: agent initialized")
    except Exception as e:
        logger.error("Phase 4 failed (agent): %s", e)

    # ── Phase 5: Messenger (optional) ────────────────────────────────
    if message_router is not None:
        try:
            await init_messenger(
                components.db, message_router, event_callback,
                vault=components.credential_vault,
            )
            # Messenger components are not stored on AppComponents by default;
            # callers can extend AppComponents or use the returned dict.
            logger.info("Phase 5 complete: messenger initialized")
        except Exception as e:
            logger.error("Phase 5 failed (messenger): %s", e)

    # ── Phase 6: Background Jobs (requires DB + Redis) ─────────────
    try:
        from breadmind.storage.bg_jobs_store import BgJobsStore
        from breadmind.tasks.manager import BackgroundJobManager
        from breadmind.tools.builtin import set_bg_job_manager

        # Only enable with real DB (not FileSettingsStore)
        if hasattr(components.db, "acquire"):
            store = BgJobsStore(components.db)
            task_cfg = getattr(config, "task", None)
            redis_url = task_cfg.redis_url if task_cfg else "redis://localhost:6379/0"
            max_monitors = task_cfg.max_concurrent_monitors if task_cfg else 10

            mgr = BackgroundJobManager(store, redis_url=redis_url, max_monitors=max_monitors)
            await mgr.recover_on_startup()

            retention = task_cfg.completed_retention_days if task_cfg else 30
            await mgr.cleanup_old_jobs(retention)

            set_bg_job_manager(mgr)
            components.bg_job_manager = mgr
            logger.info("Phase 6 complete: background jobs initialized")
        else:
            logger.info("Phase 6 skipped: background jobs require PostgreSQL")
    except Exception as e:
        logger.warning("Phase 6 failed (background jobs): %s", e)

    # ── Personal Scheduler (after messenger) ───────────────────────
    if components.adapter_registry is not None and message_router is not None:
        try:
            from breadmind.personal.proactive import PersonalScheduler
            personal_scheduler = PersonalScheduler(
                components.adapter_registry, message_router,
            )
            await personal_scheduler.start()
            components.personal_scheduler = personal_scheduler
            logger.info("PersonalScheduler started")
        except Exception as e:
            logger.warning("PersonalScheduler not started: %s", e)

    return components
