# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BreadMind is a Python-based AI infrastructure agent for managing Kubernetes, Proxmox hypervisors, and OpenWrt routers via natural language. It features multi-LLM support, 6 messenger integrations, MCP protocol support, a plugin system, and a distributed commander/worker architecture.

## Build & Development Commands

```bash
# Install in development mode (core only)
pip install -e ".[dev]"

# Install with all optional features
pip install -e ".[dev,browser,messenger,container,embeddings]"

# Run the web server
breadmind web --host 0.0.0.0 --port 8080

# Run all tests
python -m pytest tests/ -v --tb=short

# Run a single test file
python -m pytest tests/test_agent.py -v

# Run a single test function
python -m pytest tests/test_agent.py::test_function_name -v

# Run tests with coverage (CI threshold: 55%)
python -m pytest tests/ --cov=breadmind --cov-fail-under=55

# Lint
ruff check src/ tests/
```

## Architecture

### Core Loop (`src/breadmind/core/`)
`CoreAgent` orchestrates multi-turn conversations: receives user input → builds prompt (with context/memory) → calls LLM → executes tool calls via `ToolExecutor` → loops until no more tool calls or max turns reached. `SafetyGuard` intercepts dangerous commands with blacklist/approval rules. `EventBus` provides async pub/sub for cross-module communication.

### LLM Provider System (`src/breadmind/llm/`)
Abstract `LLMProvider` base with implementations for Claude (Anthropic), Gemini (Google), Grok (xAI), Ollama (local), and CLI (subprocess wrapper). `create_provider()` factory in `llm/factory.py`. Supports fallback chains for automatic provider switching on failure.

### Tool System (`src/breadmind/tools/`)
`ToolRegistry` manages tool discovery and registration. Built-in tools in `builtin.py` cover shell execution, file operations, infrastructure management. MCP tools are dynamically loaded from external servers. Tools return `ToolResult` objects.

### Web Layer (`src/breadmind/web/`)
FastAPI app with 20+ route modules. WebSocket endpoint for real-time chat. Static frontend served from `web/static/`. Routes are organized by domain (chat, settings, plugins, monitoring, etc.).

### Storage (`src/breadmind/storage/`)
PostgreSQL with pgvector extension. Async via asyncpg. `CredentialVault` for encrypted token storage. All runtime configuration (LLM keys, MCP servers, messenger tokens) stored in DB, not config files.

### Memory (`src/breadmind/memory/`)
Three-layer system: Working (session context), Episodic (past interactions), Semantic (knowledge graph with pgvector embeddings). Memory garbage collection runs periodically.

### Configuration Split
- **Static** (`config/config.yaml`): Database connection, web binding, security, network mode. Read at startup, requires restart to change.
- **Runtime** (DB via Settings UI): LLM providers/keys, MCP servers, messenger tokens, safety rules, persona, monitoring. Changed live without restart.
- **Environment** (`.env`): API keys and DB credentials as env vars, referenced by config.yaml via `${VAR:-default}` syntax.

### Plugin System (`src/breadmind/plugins/`)
Claude Code-compatible plugin format. Plugins loaded at runtime from local paths or marketplace. Plugin lifecycle: discover → load → validate → register tools.

### Messenger (`src/breadmind/messenger/`)
Gateways for Slack, Discord, Telegram, WhatsApp, Gmail, Signal. Each gateway implements a common interface. Auto-connection wizards handle OAuth/token setup.

### Network (`src/breadmind/network/`)
Distributed mode with Commander (coordinates) and Worker (executes) roles. Standalone mode is the default. Communication via WebSocket.

## Key Patterns

- **Async-first**: Nearly all I/O is async (asyncpg, aiohttp, FastAPI). Use `async/await` consistently.
- **pytest-asyncio with `auto` mode**: Tests use `asyncio_mode = "auto"` — async test functions are automatically detected without explicit markers.
- **Python 3.12+**: Uses modern Python features. CI tests against 3.12 and 3.13.
- **Jinja2 prompts**: System prompts are Jinja2 templates in `src/breadmind/prompts/`.

## Docker

```bash
# PostgreSQL only (recommended for local dev)
docker compose up -d postgres

# Full stack (PostgreSQL + BreadMind)
docker compose --profile full up -d
```

PostgreSQL uses `pgvector/pgvector:pg17` base image with vector extension pre-installed.
