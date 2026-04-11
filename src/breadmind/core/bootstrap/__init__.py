"""Application bootstrap — initializes all components from config.

Bootstrap initialization (plugin-based architecture)
=====================================================

Phase 1: Database + Credential Vault
Phase 2: Core services (LLM, MCP, Memory, etc.)
Phase 3: ServiceContainer populated with all services
Phase 4: PluginManager loads all plugins → tools registered
Phase 5: Agent initialization
Phase 6: Messenger (optional)
Phase 7: Background jobs (optional)
Phase 8: Personal scheduler (optional)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from breadmind.core.events import get_event_bus
from breadmind.plugins.container import ServiceContainer

from breadmind.core.bootstrap.components import (  # noqa: F401 — re-exported
    AppComponents,
    DatabaseComponents,
    LLMComponents,
    MemoryComponents,
    ToolComponents,
    PluginComponents,
    MonitoringComponents,
    NetworkComponents,
    PersonalComponents,
)

logger = logging.getLogger(__name__)


def _detect_package_managers() -> list[str]:
    import shutil
    candidates = ["apt", "apt-get", "dnf", "yum", "apk", "pacman", "zypper",
                   "snap", "flatpak", "brew", "winget", "choco", "scoop"]
    return [pm for pm in candidates if shutil.which(pm)]


# ── Phase 1: Database ───────────────────────────────────────────────────

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


# ── Phase 2: Core services ──────────────────────────────────────────────

async def init_core_services(config, db, provider, safety_cfg, vault=None):
    """Initialize all core services and return them in a ServiceContainer.

    This replaces the old init_tools + init_memory phases.
    Services are created here but tools are NOT registered — that happens
    via PluginManager in Phase 4.
    """
    container = ServiceContainer()

    # ── Basic services ──────────────────────────────────────────
    container.register("config", config)
    container.register("db", db)
    container.register("llm_provider", provider)

    # ── Tool Registry (empty — plugins will populate it) ────────
    from breadmind.tools.registry import ToolRegistry
    registry = ToolRegistry()
    container.register("tool_registry", registry)

    # ── Safety Guard ────────────────────────────────────────────
    from breadmind.core.safety import SafetyGuard
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )
    container.register("safety_guard", guard)

    # ── Role Registry & Orchestrator ────────────────────────────
    from breadmind.core.role_registry import RoleRegistry
    from breadmind.core.result_evaluator import ResultEvaluator
    from breadmind.core.orchestrator import Orchestrator

    role_registry = RoleRegistry()
    await role_registry.load_from_db(db)
    container.register("role_registry", role_registry)

    orchestrator = Orchestrator(
        provider=provider,
        role_registry=role_registry,
        evaluator=ResultEvaluator(),
        tool_registry=registry,
    )
    container.register("orchestrator", orchestrator)

    # ── MCP Client ──────────────────────────────────────────────
    from breadmind.tools.mcp_client import MCPClientManager
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

    container.register("mcp_manager", mcp_manager)

    # ── Registry Search Engine ──────────────────────────────────
    from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig
    search_engine = RegistrySearchEngine([
        RegistryConfig(name=r.name, type=r.type, enabled=r.enabled, url=r.url)
        for r in config.mcp.registries
    ])
    container.register("search_engine", search_engine)

    # ── Performance Tracker + Skill Store ───────────────────────
    from breadmind.core.performance import PerformanceTracker
    from breadmind.core.skill_store import SkillStore

    performance_tracker = PerformanceTracker(db=db)
    await performance_tracker.load_from_db()
    container.register("performance_tracker", performance_tracker)

    skill_store = SkillStore(db=db, tracker=performance_tracker)
    await skill_store.load_from_db()
    container.register("skill_store", skill_store)

    # Register OS-specific skills
    from breadmind.skills.os_skills import register_os_skills
    detected_pkg_managers = _detect_package_managers()
    await register_os_skills(skill_store, package_managers=detected_pkg_managers)

    # ── Tool Gap Detector ───────────────────────────────────────
    from breadmind.core.tool_gap import ToolGapDetector
    tool_gap_detector = ToolGapDetector(
        tool_registry=registry,
        mcp_manager=mcp_manager,
        search_engine=search_engine,
    )
    container.register("tool_gap_detector", tool_gap_detector)

    # ── Memory layers ───────────────────────────────────────────
    from breadmind.memory.working import WorkingMemory
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.memory.embedding import EmbeddingService

    episodic_memory = EpisodicMemory(db=db)
    semantic_memory = SemanticMemory(db=db)
    container.register("episodic_memory", episodic_memory)
    container.register("semantic_memory", semantic_memory)

    # Embedding service
    emb_cfg = config.embedding if hasattr(config, 'embedding') else None
    if emb_cfg:
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

    if embedding_service.is_available() and hasattr(db, 'setup_pgvector'):
        await db.setup_pgvector(embedding_service.dimensions)

    # ── Smart Retriever ─────────────────────────────────────────
    from breadmind.core.smart_retriever import SmartRetriever
    smart_retriever = SmartRetriever(
        embedding_service=embedding_service,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        skill_store=skill_store,
        db=db,
    )
    skill_store.set_retriever(smart_retriever)
    container.register("smart_retriever", smart_retriever)

    working_memory = WorkingMemory(db=db, provider=provider)
    container.register("working_memory", working_memory)

    # ── Profiler ────────────────────────────────────────────────
    profiler = None
    try:
        from breadmind.memory.profiler import UserProfiler
        profiler = UserProfiler(db=db)
        await profiler.load_from_db()
    except (ImportError, Exception):
        pass
    if profiler:
        container.register("profiler", profiler)

    # ── Context Builder ─────────────────────────────────────────
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
    if context_builder:
        container.register("context_builder", context_builder)

    # ── Personal assistant adapters ─────────────────────────────
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

        if context_builder:
            context_builder.register_provider(PersonalContextProvider(adapter_registry))

        container.register("adapter_registry", adapter_registry)

        from breadmind.personal.oauth import OAuthManager
        oauth_manager = OAuthManager(db, vault=vault)
        container.register("oauth_manager", oauth_manager)

        from breadmind.personal.adapters.google_calendar import GoogleCalendarAdapter
        from breadmind.personal.adapters.google_drive import GoogleDriveAdapter
        from breadmind.personal.adapters.google_contacts import GoogleContactsAdapter
        adapter_registry.register(GoogleCalendarAdapter(oauth_manager))
        adapter_registry.register(GoogleDriveAdapter(oauth_manager))
        adapter_registry.register(GoogleContactsAdapter(oauth_manager))

        from breadmind.personal.adapters.notion import NotionAdapter
        from breadmind.personal.adapters.jira import JiraAdapter
        from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter
        adapter_registry.register(NotionAdapter())
        adapter_registry.register(JiraAdapter())
        adapter_registry.register(GitHubIssuesAdapter())

        print("  Personal assistant: ready")
    except Exception as e:
        print(f"  Personal assistant: not available ({e})")

    # ── MCP Store ───────────────────────────────────────────────
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
        container.register("mcp_store", mcp_store)
        print("  MCP Store: ready")
    except Exception as e:
        print(f"  MCP Store: not available ({e})")

    # ── Credential Vault ────────────────────────────────────────
    if vault:
        container.register("credential_vault", vault)

    return {
        "container": container,
        "registry": registry,
        "guard": guard,
        "mcp_manager": mcp_manager,
        "search_engine": search_engine,
        "performance_tracker": performance_tracker,
        "skill_store": skill_store,
        "tool_gap_detector": tool_gap_detector,
        "working_memory": working_memory,
        "episodic_memory": episodic_memory,
        "semantic_memory": semantic_memory,
        "smart_retriever": smart_retriever,
        "profiler": profiler,
        "context_builder": context_builder,
        "mcp_store": mcp_store,
        "adapter_registry": adapter_registry,
        "oauth_manager": oauth_manager,
        "orchestrator": orchestrator,
    }


# ── Phase 4: Plugin loading ─────────────────────────────────────────────

async def init_plugins(container: ServiceContainer):
    """Load all builtin and user plugins. Returns PluginManager."""
    from breadmind.plugins.manager import PluginManager

    config = container.get("config")
    registry = container.get("tool_registry")

    # User plugins directory
    if os.name == 'nt':
        plugins_base = Path(os.environ.get("APPDATA", Path.home())) / "breadmind" / "plugins" / "installed"
    else:
        plugins_base = Path.home() / ".breadmind" / "plugins" / "installed"

    plugin_mgr = PluginManager(
        plugins_dir=plugins_base,
        tool_registry=registry,
        container=container,
    )

    # Load builtin plugins first (sorted by priority)
    # __file__ is now bootstrap/__init__.py, so parent.parent.parent = src/breadmind/
    builtin_dir = Path(__file__).resolve().parent.parent.parent / "plugins" / "builtin"
    builtin_count = await plugin_mgr.load_builtin(builtin_dir)
    print(f"  Builtin plugins: {builtin_count} loaded")

    # Load user-installed plugins
    await plugin_mgr.load_all()
    user_count = len(plugin_mgr.loaded_plugins) - builtin_count
    if user_count > 0:
        print(f"  User plugins: {user_count} loaded")

    total_tools = plugin_mgr.get_all_tool_count()
    print(f"  Total tools registered: {total_tools}")

    return plugin_mgr


# ── Phase 5: Agent ───────────────────────────────────────────────────────

async def init_agent(config, provider, registry, guard, db, memory_components, orchestrator=None):
    """Initialize CoreAgent with BehaviorTracker."""
    from breadmind.core.agent import CoreAgent
    from breadmind.config import DEFAULT_PERSONA
    from breadmind.core.behavior_tracker import BehaviorTracker

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

    if metrics_collector is not None and hasattr(registry, 'set_metrics_collector'):
        registry.set_metrics_collector(metrics_collector)

    # Initialize OpenTelemetry (optional)
    otel_integration = None
    try:
        otel_enabled = os.environ.get("BREADMIND_OTEL_ENABLED", "").lower() in ("1", "true")
        if otel_enabled:
            from breadmind.core.otel import init_otel, OTelConfig
            otel_config = OTelConfig(
                enabled=True,
                service_name="breadmind",
                endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
                log_user_prompts=os.environ.get("OTEL_LOG_USER_PROMPTS", "").lower() == "1",
            )
            otel_integration = init_otel(otel_config)
    except (ImportError, Exception) as e:
        logger.debug("OpenTelemetry not available: %s", e)

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
    import platform as _plat
    from datetime import datetime, timezone

    # __file__ is now bootstrap/__init__.py, so parent.parent.parent = src/breadmind/
    prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"

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
    if orchestrator is not None:
        agent_kwargs["orchestrator"] = orchestrator

    agent = CoreAgent(**agent_kwargs)

    agent._provider_name = provider_name
    agent._prompt_context = prompt_context
    agent._persona = DEFAULT_PERSONA.get("preset", "professional")

    behavior_tracker = BehaviorTracker(
        provider=provider,
        get_behavior_prompt=agent.get_behavior_prompt,
        set_behavior_prompt=agent.set_behavior_prompt,
        add_notification=agent.add_notification,
        db=db,
    )
    agent.set_behavior_tracker(behavior_tracker)

    # Environment scan
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


# ── Phase 6: Messenger ──────────────────────────────────────────────────

async def init_messenger(db, message_router, event_callback=None, vault=None):
    """Initialize messenger auto-connect, lifecycle, and security components."""
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

    results = await lifecycle.auto_start_all()
    started = [p for p, ok in results.items() if ok]
    if started:
        logger.info("Auto-started messengers: %s", started)

    return {
        "security": security,
        "lifecycle": lifecycle,
        "orchestrator": orchestrator,
    }


# ── Skill auto-discovery (background) ───────────────────────────────────

async def discover_and_install_skills(skill_store, search_engine):
    """Auto-discover skills from marketplace based on detected environment."""
    from breadmind.skills.auto_discovery import auto_discover_skills, apply_fallback_skills
    from breadmind.skills.domain_skills import detect_domains

    detected = detect_domains()
    detected_tool_names = []
    for d in detected:
        detected_tool_names.extend(d.detected_tools)

    if not detected_tool_names:
        return

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

    await apply_fallback_skills(detected_tool_names, skill_store)

    try:
        await skill_store.flush_to_db()
    except Exception:
        pass


# ── Main entry point ─────────────────────────────────────────────────────────────

async def bootstrap_all(
    config,
    config_dir: str,
    safety_cfg: dict,
    provider,
    message_router=None,
    event_callback=None,
) -> AppComponents:
    """Run all initialization phases in dependency order.

    Phase 1: Database + Credential Vault
    Phase 2: Core services -> ServiceContainer
    Phase 3: (merged into Phase 2)
    Phase 4: PluginManager loads all plugins -> tools registered
    Phase 5: Agent
    Phase 6: Messenger (optional)
    Phase 7: Background jobs
    Phase 8: Personal scheduler
    """
    from breadmind.core.bootstrap.phases import (
        init_phase_database,
        init_phase_credentials,
        init_phase_core_services,
        init_phase_plugins,
        init_phase_agent,
        init_phase_messengers,
        init_phase_background,
        init_phase_personal,
    )

    components = AppComponents(config=config, safety_cfg=safety_cfg)
    components.event_bus = get_event_bus()

    await init_phase_database(components, config, config_dir)
    await init_phase_credentials(components)
    await init_phase_core_services(components, config, provider, safety_cfg)
    await init_phase_plugins(components)
    await init_phase_agent(components, config, provider, safety_cfg)
    await init_phase_messengers(components, message_router, event_callback)
    await init_phase_background(components, config)
    await init_phase_personal(components, message_router)

    return components


# ── Legacy compatibility wrappers ────────────────────────────────────────
# main.py still calls init_tools / init_memory individually.
# These wrappers delegate to the new init_core_services + init_plugins flow
# while preserving the old return signatures.


async def init_tools(config, safety_cfg):
    """Legacy wrapper — returns (registry, guard, mcp_manager, search_engine, meta_tools).

    .. deprecated:: Use init_core_services() + init_plugins() instead.
    """
    from breadmind.tools.registry import ToolRegistry
    from breadmind.core.safety import SafetyGuard
    from breadmind.tools.mcp_client import MCPClientManager
    from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig

    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    # Register builtin tools (legacy path)
    from breadmind.tools.builtin import register_builtin_tools
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        register_builtin_tools(registry)

    # Browser tools (optional)
    try:
        from breadmind.tools.browser import register_browser_tools
        register_browser_tools(registry)
    except Exception:
        pass

    # Code delegate tool (optional)
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

    search_engine = RegistrySearchEngine([
        RegistryConfig(name=r.name, type=r.type, enabled=r.enabled, url=r.url)
        for r in config.mcp.registries
    ])

    from breadmind.tools.meta import create_meta_tools
    meta_tools = create_meta_tools(mcp_manager, search_engine)
    for func in meta_tools.values():
        registry.register(func)

    return registry, guard, mcp_manager, search_engine, meta_tools


def _register_code_delegate(registry, db) -> None:
    """Register the code_delegate tool into the registry (legacy)."""
    from breadmind.coding.tool import create_code_delegate_tool
    from breadmind.llm.base import ToolDefinition

    tool_def_dict, handler = create_code_delegate_tool(db=db)
    handler._tool_definition = ToolDefinition(
        name=tool_def_dict["name"],
        description=tool_def_dict["description"],
        parameters=tool_def_dict["parameters"],
    )
    registry.register(handler)


async def init_memory(db, provider, config, registry, mcp_manager, search_engine, vault=None):
    """Legacy wrapper — returns dict of memory components.

    .. deprecated:: Use init_core_services() instead.
    """
    from breadmind.memory.working import WorkingMemory
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.memory.embedding import EmbeddingService
    from breadmind.core.smart_retriever import SmartRetriever
    from breadmind.core.performance import PerformanceTracker
    from breadmind.core.skill_store import SkillStore
    from breadmind.core.tool_gap import ToolGapDetector
    from breadmind.tools.meta import create_expansion_tools, create_memory_tools

    performance_tracker = PerformanceTracker(db=db)
    await performance_tracker.load_from_db()

    skill_store = SkillStore(db=db, tracker=performance_tracker)
    await skill_store.load_from_db()

    from breadmind.skills.os_skills import register_os_skills
    detected_pkg_managers = _detect_package_managers()
    await register_os_skills(skill_store, package_managers=detected_pkg_managers)

    tool_gap_detector = ToolGapDetector(
        tool_registry=registry,
        mcp_manager=mcp_manager,
        search_engine=search_engine,
    )

    episodic_memory = EpisodicMemory(db=db)
    semantic_memory = SemanticMemory(db=db)

    emb_cfg = config.embedding if hasattr(config, 'embedding') else None
    if emb_cfg:
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

    expansion_tools = create_expansion_tools(
        skill_store=skill_store,
        tracker=performance_tracker,
    )
    for func in expansion_tools.values():
        registry.register(func)

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
    except Exception:
        pass

    working_memory = WorkingMemory(db=db, provider=provider)

    profiler = None
    try:
        from breadmind.memory.profiler import UserProfiler
        profiler = UserProfiler(db=db)
        await profiler.load_from_db()
    except (ImportError, Exception):
        pass

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

        if context_builder:
            context_builder.register_provider(PersonalContextProvider(adapter_registry))

        from breadmind.personal.tools import register_personal_tools
        if registry:
            register_personal_tools(registry, adapter_registry, user_id="default")

        from breadmind.personal.oauth import OAuthManager
        oauth_manager = OAuthManager(db, vault=vault)

        from breadmind.personal.adapters.google_calendar import GoogleCalendarAdapter
        from breadmind.personal.adapters.google_drive import GoogleDriveAdapter
        from breadmind.personal.adapters.google_contacts import GoogleContactsAdapter
        adapter_registry.register(GoogleCalendarAdapter(oauth_manager))
        adapter_registry.register(GoogleDriveAdapter(oauth_manager))
        adapter_registry.register(GoogleContactsAdapter(oauth_manager))

        from breadmind.personal.adapters.notion import NotionAdapter
        from breadmind.personal.adapters.jira import JiraAdapter
        from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter
        adapter_registry.register(NotionAdapter())
        adapter_registry.register(JiraAdapter())
        adapter_registry.register(GitHubIssuesAdapter())
    except Exception:
        pass

    # Register memory tools (legacy path — agent init also does this)
    mem_tools = create_memory_tools(
        episodic_memory=episodic_memory,
        profiler=profiler,
        smart_retriever=smart_retriever,
    )
    for func in mem_tools.values():
        registry.register(func)

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
