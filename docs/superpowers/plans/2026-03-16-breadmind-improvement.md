# BreadMind Comprehensive Improvement Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve BreadMind across 5 parallel streams: token optimization, architecture refactoring, web decomposition, memory/learning enhancement, and security/diagnostics.

**Architecture:** 5 independent work streams that modify non-overlapping files, merged at the end. Each stream runs in its own git worktree to avoid conflicts.

**Tech Stack:** Python 3.12+, FastAPI, asyncpg, asyncio, Anthropic SDK

---

## Stream A: Token & Context Optimization

**Owner:** agent-token
**Goal:** Reduce token waste by 40-60% through TokenCounter integration, dynamic tool filtering, and conversation summarization.

### Task A1: Conversation Summarizer

**Files:**
- Create: `src/breadmind/memory/summarizer.py`
- Test: `tests/test_summarizer.py`

- [ ] **Step 1: Create `memory/summarizer.py`**

```python
"""Conversation summarizer for context window management."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage, LLMProvider
from breadmind.llm.token_counter import TokenCounter

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "Summarize this conversation concisely. Keep all key facts, decisions, "
    "tool results, and action items. Output only the summary, no preamble."
)


class ConversationSummarizer:
    """Compress old conversation turns to fit context window."""

    def __init__(
        self,
        provider: LLMProvider,
        model: str = "",
        keep_recent: int = 10,
        target_ratio: float = 0.7,
    ):
        self._provider = provider
        self._model = model
        self._keep_recent = keep_recent
        self._target_ratio = target_ratio

    async def summarize_if_needed(
        self,
        messages: list[LLMMessage],
        tools: list | None,
        model: str = "",
    ) -> list[LLMMessage]:
        """Return messages, summarizing old turns if they exceed the target ratio of context."""
        effective_model = model or self._model or getattr(self._provider, "model_name", "claude-sonnet-4-6")
        limit = TokenCounter.get_model_limit(effective_model)
        target = int(limit * self._target_ratio)

        current_tokens = TokenCounter.estimate_messages_tokens(messages)
        if tools:
            current_tokens += TokenCounter.estimate_tools_tokens(tools)

        if current_tokens <= target:
            return messages

        # Split: system msgs | old middle | recent
        system_msgs: list[LLMMessage] = []
        idx = 0
        while idx < len(messages) and messages[idx].role == "system":
            system_msgs.append(messages[idx])
            idx += 1

        remaining = messages[idx:]
        if len(remaining) <= self._keep_recent:
            return messages

        old = remaining[: -self._keep_recent]
        recent = remaining[-self._keep_recent :]

        # Build summary text from old messages
        parts = []
        for m in old:
            if m.content and m.role in ("user", "assistant"):
                label = "User" if m.role == "user" else "Assistant"
                parts.append(f"{label}: {m.content[:500]}")
            elif m.role == "tool" and m.content:
                parts.append(f"Tool result: {m.content[:300]}")
        if not parts:
            return messages

        old_text = "\n".join(parts)
        summary_request = LLMMessage(
            role="user",
            content=f"{_SUMMARY_PROMPT}\n\n{old_text[:8000]}",
        )
        try:
            resp = await self._provider.chat([summary_request])
            summary_content = resp.content or ""
        except Exception:
            logger.warning("Summarization failed, trimming instead")
            return TokenCounter.trim_messages_to_fit(
                messages, tools, effective_model,
            )

        summary_msg = LLMMessage(
            role="system",
            content=f"[Earlier conversation summary]\n{summary_content}",
        )
        return system_msgs + [summary_msg] + recent
```

- [ ] **Step 2: Create test `tests/test_summarizer.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.memory.summarizer import ConversationSummarizer
from breadmind.llm.base import LLMMessage, LLMResponse, TokenUsage


@pytest.fixture
def mock_provider():
    p = AsyncMock()
    p.model_name = "claude-sonnet-4-6"
    p.chat = AsyncMock(return_value=LLMResponse(
        content="Summary of conversation",
        tool_calls=[],
        usage=TokenUsage(input_tokens=100, output_tokens=50),
    ))
    return p


@pytest.mark.asyncio
async def test_no_summarize_when_under_limit(mock_provider):
    summarizer = ConversationSummarizer(mock_provider, keep_recent=5)
    msgs = [
        LLMMessage(role="system", content="You are helpful."),
        LLMMessage(role="user", content="Hello"),
        LLMMessage(role="assistant", content="Hi there!"),
    ]
    result = await summarizer.summarize_if_needed(msgs, None)
    assert result == msgs
    mock_provider.chat.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_when_many_messages(mock_provider):
    summarizer = ConversationSummarizer(mock_provider, keep_recent=3, target_ratio=0.0001)
    msgs = [LLMMessage(role="system", content="System prompt")]
    for i in range(20):
        msgs.append(LLMMessage(role="user", content=f"Message {i}" * 100))
        msgs.append(LLMMessage(role="assistant", content=f"Reply {i}" * 100))
    result = await summarizer.summarize_if_needed(msgs, None)
    # Should have: system + summary + last 3 messages
    assert len(result) < len(msgs)
    assert result[0].role == "system"
    assert "[Earlier conversation summary]" in result[1].content
```

- [ ] **Step 3: Run tests**

Run: `cd /d/Projects/breadmind && python -m pytest tests/test_summarizer.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/memory/summarizer.py tests/test_summarizer.py
git commit -m "feat: add ConversationSummarizer for context window management"
```

### Task A2: Integrate TokenCounter and Summarizer into CoreAgent

**Files:**
- Modify: `src/breadmind/core/agent.py`

- [ ] **Step 1: Add token trimming and dynamic tool filtering to agent loop**

In `agent.py`, replace lines 255-274 (the tool loading and LLM call section) with:

```python
        # Filter tools to relevant subset based on message content
        all_tools = self._tools.get_all_definitions()
        tools = self._filter_relevant_tools(all_tools, message)

        for turn in range(self._max_turns):
            # Apply conversation summarization if available
            chat_messages = messages
            if self._summarizer is not None and hasattr(self._summarizer, "summarize_if_needed"):
                try:
                    chat_messages = await self._summarizer.summarize_if_needed(
                        messages, tools,
                    )
                except Exception:
                    logger.exception("Summarizer error, using original messages")
                    chat_messages = messages
            else:
                # Fallback: trim messages if exceeding context window
                from breadmind.llm.token_counter import TokenCounter
                model = getattr(self._provider, "model_name", "claude-sonnet-4-6")
                if not TokenCounter.fits_in_context(chat_messages, tools, model):
                    chat_messages = TokenCounter.trim_messages_to_fit(
                        chat_messages, tools, model,
                    )
                    logger.warning("Trimmed messages to fit context window")

            await self._notify_progress("thinking", "")

            t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self._provider.chat(messages=chat_messages, tools=tools or None),
                    timeout=self._chat_timeout,
                )
```

- [ ] **Step 2: Add `_filter_relevant_tools` method to CoreAgent**

Add after `_safe_analyze` method:

```python
    def _filter_relevant_tools(
        self, tools: list, message: str, max_tools: int = 30,
    ) -> list:
        """Filter tools to a relevant subset based on message content.

        Always includes: shell_exec, web_search, file_read, file_write, browser,
        mcp_search, mcp_install, mcp_list, skill_manage.
        For other tools, score by keyword overlap with the message.
        """
        ALWAYS_INCLUDE = {
            "shell_exec", "web_search", "file_read", "file_write",
            "browser", "mcp_search", "mcp_install", "mcp_list",
            "skill_manage", "memory_save", "memory_search",
            "swarm_role", "messenger_connect",
        }

        if len(tools) <= max_tools:
            return tools

        essential = []
        candidates = []
        msg_lower = message.lower()

        for t in tools:
            if t.name in ALWAYS_INCLUDE:
                essential.append(t)
            else:
                # Score by name/description overlap
                score = 0
                name_words = set(t.name.lower().replace("_", " ").split())
                desc_words = set((t.description or "").lower().split())
                msg_words = set(msg_lower.split())
                score = len(msg_words & name_words) * 3 + len(msg_words & desc_words)
                candidates.append((score, t))

        candidates.sort(key=lambda x: x[0], reverse=True)
        remaining_slots = max_tools - len(essential)
        selected = essential + [t for _, t in candidates[:remaining_slots]]
        return selected
```

- [ ] **Step 3: Wire summarizer in `main.py`**

In `main.py`, after the agent creation (line ~398), add:

```python
    # Wire ConversationSummarizer
    try:
        from breadmind.memory.summarizer import ConversationSummarizer
        summarizer = ConversationSummarizer(
            provider=provider,
            keep_recent=10,
            target_ratio=0.7,
        )
        agent._summarizer = summarizer
    except Exception:
        pass
```

- [ ] **Step 4: Run existing agent tests**

Run: `cd /d/Projects/breadmind && python -m pytest tests/test_agent.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/agent.py src/breadmind/main.py
git commit -m "feat: integrate TokenCounter trimming, dynamic tool filtering, and summarizer into agent loop"
```

---

## Stream B: main.py Refactoring

**Owner:** agent-bootstrap
**Goal:** Extract initialization logic from 587-line `run()` function into an AppFactory pattern.

### Task B1: Create AppFactory (Bootstrap Module)

**Files:**
- Create: `src/breadmind/core/bootstrap.py`
- Modify: `src/breadmind/main.py`
- Test: `tests/test_bootstrap.py`

- [ ] **Step 1: Create `core/bootstrap.py`**

```python
"""Application bootstrap — initializes all components from config."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AppComponents:
    """Container for all initialized application components."""
    config: Any
    db: Any
    provider: Any
    registry: Any
    guard: Any
    agent: Any
    working_memory: Any
    monitoring_engine: Any
    mcp_manager: Any
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
    return db


async def init_tools(config, db, provider):
    """Initialize tool registry, MCP, and meta tools."""
    from breadmind.tools.registry import ToolRegistry
    from breadmind.core.safety import SafetyGuard
    from breadmind.config import load_safety_config
    from breadmind.tools.builtin import shell_exec, web_search, file_read, file_write, messenger_connect, swarm_role
    from breadmind.tools.mcp_client import MCPClientManager
    from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig
    from breadmind.tools.meta import create_meta_tools

    safety_cfg = load_safety_config(os.path.dirname(str(config)))
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

    return registry, guard, mcp_manager, search_engine, safety_cfg, meta_tools


async def init_memory(db, provider, config):
    """Initialize memory layers and SmartRetriever."""
    from breadmind.memory.working import WorkingMemory
    from breadmind.memory.episodic import EpisodicMemory
    from breadmind.memory.semantic import SemanticMemory
    from breadmind.memory.embedding import EmbeddingService
    from breadmind.core.smart_retriever import SmartRetriever
    from breadmind.core.performance import PerformanceTracker
    from breadmind.core.skill_store import SkillStore

    working_memory = WorkingMemory(db=db)
    episodic_memory = EpisodicMemory(db=db)
    semantic_memory = SemanticMemory(db=db)
    embedding_service = EmbeddingService()

    performance_tracker = PerformanceTracker(db=db)
    await performance_tracker.load_from_db()

    skill_store = SkillStore(db=db, tracker=performance_tracker)
    await skill_store.load_from_db()

    smart_retriever = SmartRetriever(
        embedding_service=embedding_service,
        episodic_memory=episodic_memory,
        semantic_memory=semantic_memory,
        skill_store=skill_store,
        db=db,
    )
    skill_store.set_retriever(smart_retriever)

    # Context builder
    context_builder = None
    try:
        from breadmind.memory.context_builder import ContextBuilder
        profiler = None
        try:
            from breadmind.memory.profiler import UserProfiler
            profiler = UserProfiler(db=db)
            await profiler.load_from_db()
        except Exception:
            pass

        context_builder = ContextBuilder(
            working_memory=working_memory,
            episodic_memory=episodic_memory,
            semantic_memory=semantic_memory,
            profiler=profiler,
            max_context_tokens=4000,
            skill_store=skill_store,
        )
    except Exception:
        profiler = None

    return {
        "working_memory": working_memory,
        "episodic_memory": episodic_memory,
        "semantic_memory": semantic_memory,
        "embedding_service": embedding_service,
        "smart_retriever": smart_retriever,
        "performance_tracker": performance_tracker,
        "skill_store": skill_store,
        "context_builder": context_builder,
        "profiler": profiler,
    }


async def init_agent(config, provider, registry, guard, db, memory_components):
    """Initialize CoreAgent with all components."""
    from breadmind.core.agent import CoreAgent
    from breadmind.config import build_system_prompt, DEFAULT_PERSONA
    from breadmind.core.behavior_tracker import BehaviorTracker
    from breadmind.tools.meta import create_expansion_tools, create_memory_tools
    from breadmind.core.tool_gap import ToolGapDetector

    # Expansion tools
    expansion_tools = create_expansion_tools(
        skill_store=memory_components["skill_store"],
        tracker=memory_components["performance_tracker"],
    )
    for func in expansion_tools.values():
        registry.register(func)

    # Memory tools
    mem_tools = create_memory_tools(
        episodic_memory=memory_components["episodic_memory"],
        profiler=memory_components.get("profiler"),
        smart_retriever=memory_components["smart_retriever"],
    )
    for func in mem_tools.values():
        registry.register(func)

    # Tool gap detector
    tool_gap_detector = ToolGapDetector(
        tool_registry=registry,
        mcp_manager=None,  # wired later
        search_engine=None,
    )

    # Load saved behavior prompt
    saved_behavior_prompt = None
    if db is not None:
        try:
            bp_data = await db.get_setting("behavior_prompt")
            if bp_data and "prompt" in bp_data:
                saved = bp_data["prompt"]
                if "Autonomous Problem Solving" in saved:
                    saved_behavior_prompt = saved
        except Exception:
            pass

    system_prompt = build_system_prompt(
        DEFAULT_PERSONA, behavior_prompt=saved_behavior_prompt,
    )

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        system_prompt=system_prompt,
        max_turns=config.llm.tool_call_max_turns,
        working_memory=memory_components["working_memory"],
        tool_gap_detector=tool_gap_detector,
        context_builder=memory_components.get("context_builder"),
        behavior_prompt=saved_behavior_prompt,
    )

    # Wire BehaviorTracker
    behavior_tracker = BehaviorTracker(
        provider=provider,
        get_behavior_prompt=agent.get_behavior_prompt,
        set_behavior_prompt=agent.set_behavior_prompt,
        add_notification=agent.add_notification,
        db=db,
    )
    agent.set_behavior_tracker(behavior_tracker)

    # Wire Summarizer
    try:
        from breadmind.memory.summarizer import ConversationSummarizer
        agent._summarizer = ConversationSummarizer(provider=provider)
    except Exception:
        pass

    return agent, behavior_tracker
```

- [ ] **Step 2: Simplify `main.py` to use bootstrap**

Replace the body of `run()` (lines 100-577) with calls to bootstrap functions, reducing it to ~120 lines. Keep the CLI arg parsing, signal handling, and web server startup, but delegate all component initialization to `bootstrap.py`.

```python
async def run():
    args = _parse_args()
    config_dir = args.config_dir or get_default_config_dir()

    # Load config
    if os.path.isdir(config_dir) and os.path.exists(os.path.join(config_dir, "config.yaml")):
        config = load_config(config_dir)
    elif os.path.isdir("config"):
        config = load_config("config")
        config_dir = "config"
    else:
        config = load_config(config_dir)
    config.validate()

    env_file = os.path.join(config_dir, ".env")
    set_env_file_path(env_file)
    load_env_file(env_file)

    log_level = args.log_level or config.logging.level
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    mode = getattr(args, "mode", "standalone")
    if mode == "worker":
        await run_worker(config, args)
        return

    # Initialize all components via bootstrap
    from breadmind.core.bootstrap import init_database, init_tools, init_memory, init_agent

    db = await init_database(config, config_dir)
    provider = create_provider(config)

    if not args.web:
        from breadmind.core.setup_wizard import is_first_run_async, run_cli_wizard
        if await is_first_run_async(db):
            await run_cli_wizard(db, config)

    registry, guard, mcp_manager, search_engine, safety_cfg, meta_tools = await init_tools(config, db, provider)
    memory_components = await init_memory(db, provider, config)
    agent, behavior_tracker = await init_agent(config, provider, registry, guard, db, memory_components)

    # ... rest of startup (monitoring, web server, etc.) stays similar but shorter
```

- [ ] **Step 3: Run tests**

Run: `cd /d/Projects/breadmind && python -m pytest tests/test_agent.py tests/test_config_mcp.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/core/bootstrap.py src/breadmind/main.py
git commit -m "refactor: extract main.py initialization into core/bootstrap.py AppFactory"
```

---

## Stream C: web/app.py Decomposition

**Owner:** agent-web
**Goal:** Split 2429-line web/app.py into focused route modules (~300 lines each).

### Task C1: Create Route Modules

**Files:**
- Create: `src/breadmind/web/routes/__init__.py`
- Create: `src/breadmind/web/routes/chat.py` — chat, sessions, websocket
- Create: `src/breadmind/web/routes/config.py` — all /api/config/* endpoints
- Create: `src/breadmind/web/routes/tools.py` — tools, approvals
- Create: `src/breadmind/web/routes/mcp.py` — MCP search, install, servers
- Create: `src/breadmind/web/routes/monitoring.py` — monitoring, metrics, audit, usage
- Create: `src/breadmind/web/routes/swarm.py` — swarm, skills, performance, team
- Create: `src/breadmind/web/routes/system.py` — setup, auth, update, scheduler, webhook, container
- Modify: `src/breadmind/web/app.py` — reduce to ~200 lines (WebApp class + router registration)

- [ ] **Step 1: Create `web/routes/__init__.py`**

```python
"""Web route modules for BreadMind."""
```

- [ ] **Step 2: Create route modules**

Each route module follows this pattern:

```python
# src/breadmind/web/routes/chat.py
"""Chat and session routes."""
import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def setup_chat_routes(router: APIRouter, app_state):
    """Register chat routes. app_state is the WebApp instance."""

    @router.get("/api/sessions")
    async def list_sessions():
        # ... move existing code from app.py lines 2292-2296
        pass

    @router.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        # ... move from app.py lines 2298-2302
        pass

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        # ... move from app.py lines 2304-2308
        pass

    @router.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        # ... move from app.py lines 2310-end
        pass
```

The agent should move endpoints from app.py's `_setup_routes()` into the appropriate route module, grouping by domain:

- **chat.py**: `/api/sessions/*`, `/ws/chat`
- **config.py**: `/api/config/*`, `/api/config/persona`, `/api/config/prompts`, `/api/config/api-keys`, `/api/config/provider`, `/api/config/models/*`, `/api/config/mcp`, `/api/config/safety/*`, `/api/config/markets/*`, `/api/config/monitoring/*`, `/api/config/messenger`, `/api/config/memory`, `/api/config/tool-security`, `/api/config/timeouts`, `/api/config/logging`, `/api/config/settings-status`
- **tools.py**: `/api/tools`, `/api/approvals/*`
- **mcp.py**: `/api/mcp/*`, `/api/skills/search`, `/api/skills/featured`
- **monitoring.py**: `/api/monitoring/*`, `/api/usage`, `/api/audit`, `/api/metrics`
- **swarm.py**: `/api/swarm/*`, `/api/skills` (CRUD), `/api/performance/*`
- **system.py**: `/api/setup/*`, `/api/auth/*`, `/api/update/*`, `/api/system/*`, `/api/scheduler/*`, `/api/subagent/*`, `/api/webhook/*`, `/api/container/*`, `/api/messenger/*` (platform routes), `/health`

- [ ] **Step 3: Modify `web/app.py` to register routers**

Replace `_setup_routes()` with router registration:

```python
def _setup_routes(self):
    app = self.app

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Register route modules
    from breadmind.web.routes import chat, config, tools, mcp, monitoring, swarm, system

    chat.setup_chat_routes(chat.router, self)
    config.setup_config_routes(config.router, self)
    tools.setup_tools_routes(tools.router, self)
    mcp.setup_mcp_routes(mcp.router, self)
    monitoring.setup_monitoring_routes(monitoring.router, self)
    swarm.setup_swarm_routes(swarm.router, self)
    system.setup_system_routes(system.router, self)

    for r in [chat.router, config.router, tools.router, mcp.router,
              monitoring.router, swarm.router, system.router]:
        app.include_router(r)

    # Root HTML page
    @app.get("/", response_class=HTMLResponse)
    async def serve_ui():
        index_path = static_dir / "index.html"
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run web tests**

Run: `cd /d/Projects/breadmind && python -m pytest tests/test_web.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/web/routes/ src/breadmind/web/app.py
git commit -m "refactor: decompose web/app.py into 7 route modules"
```

---

## Stream D: Memory & Learning Enhancement

**Owner:** agent-memory
**Goal:** Add Reflexion pattern, success trajectory storage, MemGPT-style memory tools, and BehaviorTracker A/B versioning.

### Task D1: Reflexion Pattern

**Files:**
- Create: `src/breadmind/core/reflexion.py`
- Test: `tests/test_reflexion.py`

- [ ] **Step 1: Create `core/reflexion.py`**

```python
"""Reflexion pattern — learn from task failures via self-reflection."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMMessage, LLMProvider

if TYPE_CHECKING:
    from breadmind.memory.episodic import EpisodicMemory

logger = logging.getLogger(__name__)

_REFLECT_PROMPT = (
    "A task just failed. Analyze what went wrong and write a concise lesson "
    "(1-3 sentences) that would help avoid this failure in the future.\n\n"
    "Task: {task}\n"
    "Error: {error}\n"
    "Context: {context}\n\n"
    "Write ONLY the lesson, no preamble."
)

_RECALL_PROMPT = (
    "Check if any of these past lessons are relevant to the current task.\n\n"
    "Current task: {task}\n\n"
    "Past lessons:\n{lessons}\n\n"
    "Return ONLY the relevant lessons (copy them exactly), one per line. "
    "If none are relevant, return NONE."
)


class ReflexionEngine:
    """Learn from failures and inject lessons into future tasks."""

    def __init__(
        self,
        provider: LLMProvider,
        episodic_memory: EpisodicMemory,
    ):
        self._provider = provider
        self._episodic = episodic_memory

    async def reflect_on_failure(
        self,
        task_description: str,
        error_message: str,
        context: str = "",
    ) -> str | None:
        """Generate and store a lesson from a failed task."""
        prompt = _REFLECT_PROMPT.format(
            task=task_description,
            error=error_message[:500],
            context=context[:500],
        )
        try:
            resp = await self._provider.chat([
                LLMMessage(role="user", content=prompt),
            ])
            lesson = (resp.content or "").strip()
            if not lesson or len(lesson) < 10:
                return None

            # Store lesson in episodic memory
            await self._episodic.add_note(
                content=f"[Lesson] {lesson}",
                keywords=self._extract_keywords(task_description),
                tags=["reflexion", "lesson"],
                context_description=f"Failure reflection: {task_description[:100]}",
            )
            logger.info(f"Reflexion lesson stored: {lesson[:100]}")
            return lesson
        except Exception:
            logger.exception("Reflexion failed")
            return None

    async def recall_lessons(
        self, task_description: str, limit: int = 5,
    ) -> list[str]:
        """Retrieve relevant past lessons for a task."""
        keywords = self._extract_keywords(task_description)
        if not keywords:
            return []

        notes = await self._episodic.search_by_tags(["reflexion"], limit=limit * 2)
        if not notes:
            return []

        # Filter by keyword relevance
        keyword_set = set(k.lower() for k in keywords)
        scored = []
        for note in notes:
            note_keywords = set(k.lower() for k in (note.keywords or []))
            overlap = len(keyword_set & note_keywords)
            if overlap > 0:
                scored.append((overlap * note.decay_weight, note.content))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [content for _, content in scored[:limit]]

    async def store_success(
        self, task_description: str, result_summary: str,
    ) -> None:
        """Store a successful task trajectory for future reference."""
        await self._episodic.add_note(
            content=f"[Success] Task: {task_description}\nResult: {result_summary[:300]}",
            keywords=self._extract_keywords(task_description),
            tags=["reflexion", "success_trajectory"],
            context_description=f"Successful task: {task_description[:100]}",
        )

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        import re
        words = re.findall(r"[a-zA-Z0-9._-]+", text.lower())
        stopwords = {"the", "a", "an", "is", "are", "to", "of", "in", "for", "and", "or", "it", "this"}
        return [w for w in words if len(w) > 2 and w not in stopwords][:10]
```

- [ ] **Step 2: Create test `tests/test_reflexion.py`**

```python
import pytest
from unittest.mock import AsyncMock
from breadmind.core.reflexion import ReflexionEngine
from breadmind.llm.base import LLMResponse, TokenUsage
from breadmind.storage.models import EpisodicNote


@pytest.fixture
def engine():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="Always check pod status before scaling.",
        tool_calls=[], usage=TokenUsage(input_tokens=50, output_tokens=20),
    ))
    episodic = AsyncMock()
    episodic.add_note = AsyncMock(return_value=EpisodicNote(
        content="test", keywords=[], tags=[], context_description="", id=1,
    ))
    episodic.search_by_tags = AsyncMock(return_value=[])
    return ReflexionEngine(provider, episodic)


@pytest.mark.asyncio
async def test_reflect_on_failure(engine):
    lesson = await engine.reflect_on_failure(
        "Scale deployment nginx to 5 replicas",
        "Pod quota exceeded",
    )
    assert lesson is not None
    assert len(lesson) > 10
    engine._episodic.add_note.assert_called_once()


@pytest.mark.asyncio
async def test_store_success(engine):
    await engine.store_success("Deploy nginx", "Successfully deployed 3 replicas")
    engine._episodic.add_note.assert_called_once()
    call_kwargs = engine._episodic.add_note.call_args
    assert "success_trajectory" in call_kwargs.kwargs["tags"]
```

- [ ] **Step 3: Run tests and commit**

```bash
cd /d/Projects/breadmind
python -m pytest tests/test_reflexion.py -v
git add src/breadmind/core/reflexion.py tests/test_reflexion.py
git commit -m "feat: add Reflexion engine for learning from task failures"
```

### Task D2: BehaviorTracker A/B Versioning

**Files:**
- Modify: `src/breadmind/core/behavior_tracker.py`

- [ ] **Step 1: Add version tracking to BehaviorTracker**

Add after `self._lock` in `__init__`:

```python
        self._prompt_versions: list[dict] = []
        self._current_version: int = 0
        self._effectiveness: dict[int, list[float]] = {}
```

- [ ] **Step 2: Track versions in `analyze()` method**

After `self._set_behavior_prompt(new_prompt)` (line ~215), add:

```python
            self._current_version += 1
            self._prompt_versions.append({
                "version": self._current_version,
                "prompt": new_prompt,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metrics_snapshot": {
                    "tool_success_rate": (
                        metrics["tool_success_count"] /
                        max(metrics["tool_call_count"], 1)
                    ),
                    "text_only": metrics["text_only_response"],
                    "negative_feedback": metrics["negative_feedback"],
                },
            })
            # Keep last 20 versions
            if len(self._prompt_versions) > 20:
                self._prompt_versions = self._prompt_versions[-20:]
```

- [ ] **Step 3: Add effectiveness recording method**

```python
    def record_effectiveness(self, success_rate: float, text_only: bool):
        """Record effectiveness of current prompt version."""
        ver = self._current_version
        if ver not in self._effectiveness:
            self._effectiveness[ver] = []
        self._effectiveness[ver].append(1.0 if not text_only else 0.0)

    def get_version_history(self) -> list[dict]:
        """Return prompt version history with effectiveness scores."""
        result = []
        for v in self._prompt_versions:
            ver = v["version"]
            scores = self._effectiveness.get(ver, [])
            avg = sum(scores) / len(scores) if scores else None
            result.append({**v, "avg_effectiveness": avg, "sample_count": len(scores)})
        return result
```

- [ ] **Step 4: Wire effectiveness recording in agent.py**

In `agent.py`, in the `handle_message` method, before the behavior tracker fire-and-forget (line ~323), add:

```python
                # Record effectiveness for current behavior prompt version
                if self._behavior_tracker and hasattr(self._behavior_tracker, 'record_effectiveness'):
                    has_tools = any(m.role == "tool" for m in messages)
                    text_only = not has_tools
                    self._behavior_tracker.record_effectiveness(
                        success_rate=1.0, text_only=text_only,
                    )
```

- [ ] **Step 5: Run tests and commit**

```bash
cd /d/Projects/breadmind
python -m pytest tests/test_behavior_tracker.py -v
git add src/breadmind/core/behavior_tracker.py
git commit -m "feat: add A/B version tracking to BehaviorTracker"
```

### Task D3: MemGPT-style Memory Tools

**Files:**
- Create: `src/breadmind/tools/agent_memory.py`

- [ ] **Step 1: Create agent-accessible memory tools**

```python
"""MemGPT-style memory tools — let the agent manage its own memory."""
from __future__ import annotations

from breadmind.tools.registry import tool


def create_agent_memory_tools(episodic_memory, semantic_memory):
    """Create memory tools that the agent can call to manage its own memory."""

    @tool(
        description=(
            "Save important information to long-term memory. "
            "Use this to remember facts, lessons, user preferences, "
            "infrastructure details, or anything worth recalling later. "
            "Provide descriptive keywords for future retrieval."
        )
    )
    async def memory_save(
        content: str,
        keywords: str = "",
        category: str = "general",
    ) -> str:
        tags = ["agent_memory", category]
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
        note = await episodic_memory.add_note(
            content=content,
            keywords=kw_list,
            tags=tags,
            context_description=f"Agent memory: {category}",
        )
        return f"Saved to memory (id={note.id}): {content[:100]}"

    @tool(
        description=(
            "Search long-term memory for relevant information. "
            "Use keywords to find past lessons, decisions, infrastructure facts, "
            "or anything previously saved with memory_save."
        )
    )
    async def memory_search(
        keywords: str,
        limit: int = 5,
    ) -> str:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        if not kw_list:
            return "No keywords provided."
        notes = await episodic_memory.search_by_keywords(kw_list, limit=limit)
        if not notes:
            return "No matching memories found."
        lines = []
        for n in notes:
            lines.append(f"[id={n.id}] {n.content}")
        return "\n".join(lines)

    @tool(
        description=(
            "List known infrastructure entities from the knowledge graph. "
            "Search by name or type (ip_address, hostname, infrastructure, role, skill)."
        )
    )
    async def memory_entities(
        search: str = "",
        entity_type: str = "",
        limit: int = 10,
    ) -> str:
        entities = await semantic_memory.find_entities(
            entity_type=entity_type or None,
            name_contains=search or None,
        )
        if not entities:
            return "No entities found."
        lines = []
        for e in entities[:limit]:
            lines.append(f"[{e.entity_type}] {e.name}: {e.properties}")
        return "\n".join(lines)

    return {
        "memory_save": memory_save,
        "memory_search": memory_search,
        "memory_entities": memory_entities,
    }
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/tools/agent_memory.py
git commit -m "feat: add MemGPT-style memory tools (save/search/entities) for agent self-directed memory"
```

---

## Stream E: Security & Diagnostics

**Owner:** agent-security
**Goal:** Add lightweight K8sGPT-style analyzers and shell exec sandboxing foundation.

### Task E1: Infrastructure Analyzers

**Files:**
- Create: `src/breadmind/core/analyzers.py`
- Test: `tests/test_analyzers.py`

- [ ] **Step 1: Create `core/analyzers.py`**

```python
"""K8sGPT-style lightweight analyzers — diagnose without LLM calls."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticResult:
    source: str  # "k8s", "proxmox", "openwrt", "system"
    severity: str  # "info", "warning", "critical"
    title: str
    details: str
    suggestion: str = ""


class BaseAnalyzer:
    """Base class for infrastructure analyzers."""
    name: str = "base"
    source: str = "system"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        raise NotImplementedError


class DiskUsageAnalyzer(BaseAnalyzer):
    name = "disk_usage"
    source = "system"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        results = []
        try:
            output = await tool_executor("shell_exec", {"command": "df -h --output=pcent,target 2>/dev/null || wmic logicaldisk get size,freespace,caption"})
            if not output.success:
                return results
            for line in output.output.split("\n"):
                match = re.search(r"(\d+)%\s+(.+)", line.strip())
                if match:
                    usage = int(match.group(1))
                    mount = match.group(2).strip()
                    if usage >= 90:
                        results.append(DiagnosticResult(
                            source="system", severity="critical",
                            title=f"Disk almost full: {mount} ({usage}%)",
                            details=f"Mount point {mount} is at {usage}% capacity.",
                            suggestion=f"Clean up disk space on {mount} or extend the volume.",
                        ))
                    elif usage >= 80:
                        results.append(DiagnosticResult(
                            source="system", severity="warning",
                            title=f"Disk usage high: {mount} ({usage}%)",
                            details=f"Mount point {mount} is at {usage}% capacity.",
                            suggestion=f"Monitor disk usage on {mount}.",
                        ))
        except Exception as e:
            logger.debug(f"DiskUsageAnalyzer error: {e}")
        return results


class MemoryUsageAnalyzer(BaseAnalyzer):
    name = "memory_usage"
    source = "system"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        results = []
        try:
            output = await tool_executor("shell_exec", {"command": "free -m 2>/dev/null || systeminfo | findstr Memory"})
            if not output.success:
                return results
            # Parse Linux 'free' output
            for line in output.output.split("\n"):
                if line.startswith("Mem:"):
                    parts = line.split()
                    if len(parts) >= 3:
                        total = int(parts[1])
                        used = int(parts[2])
                        pct = (used / total * 100) if total > 0 else 0
                        if pct >= 90:
                            results.append(DiagnosticResult(
                                source="system", severity="critical",
                                title=f"Memory critically low ({pct:.0f}% used)",
                                details=f"Used: {used}MB / {total}MB",
                                suggestion="Identify and stop memory-heavy processes, or add more RAM.",
                            ))
                        elif pct >= 80:
                            results.append(DiagnosticResult(
                                source="system", severity="warning",
                                title=f"Memory usage high ({pct:.0f}% used)",
                                details=f"Used: {used}MB / {total}MB",
                                suggestion="Monitor memory usage trends.",
                            ))
        except Exception as e:
            logger.debug(f"MemoryUsageAnalyzer error: {e}")
        return results


class K8sPodAnalyzer(BaseAnalyzer):
    name = "k8s_pods"
    source = "k8s"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        results = []
        try:
            output = await tool_executor("shell_exec", {
                "command": "kubectl get pods --all-namespaces --field-selector=status.phase!=Running,status.phase!=Succeeded -o wide 2>/dev/null"
            })
            if not output.success or "No resources" in output.output:
                return results
            lines = [l for l in output.output.strip().split("\n") if l and not l.startswith("NAMESPACE")]
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    ns, pod, ready, status = parts[0], parts[1], parts[2], parts[3]
                    if status in ("CrashLoopBackOff", "Error", "OOMKilled", "ImagePullBackOff"):
                        results.append(DiagnosticResult(
                            source="k8s", severity="critical",
                            title=f"Pod {ns}/{pod} in {status}",
                            details=f"Ready: {ready}, Status: {status}",
                            suggestion=f"kubectl describe pod {pod} -n {ns} && kubectl logs {pod} -n {ns} --tail=50",
                        ))
                    elif status == "Pending":
                        results.append(DiagnosticResult(
                            source="k8s", severity="warning",
                            title=f"Pod {ns}/{pod} stuck Pending",
                            details=f"Ready: {ready}",
                            suggestion=f"Check resource quotas and node capacity: kubectl describe pod {pod} -n {ns}",
                        ))
        except Exception as e:
            logger.debug(f"K8sPodAnalyzer error: {e}")
        return results


# Registry of all analyzers
ALL_ANALYZERS: list[type[BaseAnalyzer]] = [
    DiskUsageAnalyzer,
    MemoryUsageAnalyzer,
    K8sPodAnalyzer,
]


async def run_all_analyzers(tool_executor) -> list[DiagnosticResult]:
    """Run all registered analyzers and collect results."""
    all_results = []
    tasks = [cls().analyze(tool_executor) for cls in ALL_ANALYZERS]
    for coro in asyncio.as_completed(tasks):
        try:
            results = await coro
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"Analyzer failed: {e}")
    # Sort by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    all_results.sort(key=lambda r: severity_order.get(r.severity, 3))
    return all_results
```

- [ ] **Step 2: Create test `tests/test_analyzers.py`**

```python
import pytest
from unittest.mock import AsyncMock
from breadmind.core.analyzers import (
    DiskUsageAnalyzer, MemoryUsageAnalyzer, K8sPodAnalyzer, run_all_analyzers,
)
from breadmind.tools.registry import ToolResult


@pytest.fixture
def mock_executor():
    async def executor(tool_name, args):
        return ToolResult(success=True, output="")
    return executor


@pytest.mark.asyncio
async def test_disk_usage_critical():
    async def executor(tool_name, args):
        return ToolResult(success=True, output=" 95% /\n 50% /home\n")
    results = await DiskUsageAnalyzer().analyze(executor)
    assert len(results) == 1
    assert results[0].severity == "critical"
    assert "95%" in results[0].title


@pytest.mark.asyncio
async def test_k8s_pod_crashloop():
    async def executor(tool_name, args):
        return ToolResult(success=True, output=(
            "NAMESPACE   NAME        READY   STATUS             RESTARTS\n"
            "default     nginx-abc   0/1     CrashLoopBackOff   5\n"
        ))
    results = await K8sPodAnalyzer().analyze(executor)
    assert len(results) == 1
    assert results[0].severity == "critical"
    assert "CrashLoopBackOff" in results[0].title


@pytest.mark.asyncio
async def test_run_all_analyzers(mock_executor):
    results = await run_all_analyzers(mock_executor)
    assert isinstance(results, list)
```

- [ ] **Step 3: Create analyzer tool for agent**

Add to `tools/meta.py` or create `tools/diagnostics.py`:

```python
@tool(description="Run infrastructure health checks without LLM calls. Checks disk, memory, K8s pods. Returns diagnostics with severity and suggestions.")
async def health_check() -> str:
    from breadmind.core.analyzers import run_all_analyzers
    # tool_executor will be wired at registration time
    results = await run_all_analyzers(_tool_executor)
    if not results:
        return "All checks passed. No issues detected."
    lines = []
    for r in results:
        emoji = {"critical": "[CRITICAL]", "warning": "[WARNING]", "info": "[INFO]"}
        lines.append(f"{emoji.get(r.severity, '')} {r.title}\n  {r.details}\n  Suggestion: {r.suggestion}")
    return "\n\n".join(lines)
```

- [ ] **Step 4: Run tests and commit**

```bash
cd /d/Projects/breadmind
python -m pytest tests/test_analyzers.py -v
git add src/breadmind/core/analyzers.py tests/test_analyzers.py
git commit -m "feat: add K8sGPT-style infrastructure analyzers (disk, memory, k8s pods)"
```

### Task E2: Shell Exec Sandbox Foundation

**Files:**
- Create: `src/breadmind/core/sandbox.py`

- [ ] **Step 1: Create sandbox module**

```python
"""Sandbox for shell command execution — foundation for container isolation."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Commands that should never be executed without explicit approval
DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/",           # rm -rf /
    r"\bmkfs\b",                  # format filesystem
    r"\bdd\s+.*of=/dev/",        # dd to device
    r":(){.*};:",                  # fork bomb
    r"\bshutdown\b",             # shutdown
    r"\breboot\b",               # reboot (without context)
    r"\biptables\s+-F\b",        # flush iptables
    r"\bkubectl\s+delete\s+.*--all", # kubectl delete --all
]


@dataclass
class SandboxConfig:
    max_execution_time: int = 30  # seconds
    max_output_size: int = 50_000  # chars
    allow_network: bool = True
    blocked_patterns: list[str] | None = None


class CommandSandbox:
    """Validate and execute shell commands with safety checks."""

    def __init__(self, config: SandboxConfig | None = None):
        self._config = config or SandboxConfig()
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (self._config.blocked_patterns or DANGEROUS_PATTERNS)
        ]

    def validate(self, command: str) -> tuple[bool, str]:
        """Check if a command is safe to execute. Returns (is_safe, reason)."""
        for pattern in self._compiled_patterns:
            if pattern.search(command):
                return False, f"Command matches dangerous pattern: {pattern.pattern}"
        return True, "ok"

    async def execute(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> tuple[bool, str]:
        """Execute a command with timeout and output limits."""
        is_safe, reason = self.validate(command)
        if not is_safe:
            return False, f"[BLOCKED] {reason}"

        effective_timeout = timeout or self._config.max_execution_time
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
            output = stdout.decode("utf-8", errors="replace")
            if len(output) > self._config.max_output_size:
                output = output[: self._config.max_output_size] + "\n[...truncated]"
            return proc.returncode == 0, output
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return False, f"Command timed out after {effective_timeout}s"
        except Exception as e:
            return False, f"Execution error: {e}"
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/core/sandbox.py
git commit -m "feat: add CommandSandbox for validated shell execution"
```

---

## Merge Phase: Integration

**Owner:** main agent (after all streams complete)

### Task M1: Merge All Streams

- [ ] **Step 1: Merge worktree branches into master**
- [ ] **Step 2: Wire new components in bootstrap.py**
  - Register `agent_memory` tools
  - Wire `ReflexionEngine` into agent
  - Wire `CommandSandbox` into shell_exec
  - Register `health_check` tool
- [ ] **Step 3: Run full test suite**

```bash
cd /d/Projects/breadmind
python -m pytest tests/ -v --tb=short
```

- [ ] **Step 4: Final commit**

```bash
git commit -m "feat: integrate all improvement streams — token optimization, architecture refactor, memory enhancement, security"
```
