# Plugin System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code 플러그인 포맷 호환 플러그인 시스템 + 마켓플레이스. 기존 하드코딩 코딩 어댑터를 선언적 플러그인으로 전환.

**Architecture:** PluginManifest (plugin.json 파싱) → PluginLoader (컴포넌트별 로드) → PluginManager (라이프사이클) → MarketplaceClient (원격 레지스트리)

**Tech Stack:** Python 3.12+, asyncio, aiohttp (existing), json, pathlib

**Spec:** `docs/superpowers/specs/2026-03-19-plugin-system-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/breadmind/plugins/__init__.py` | Package init, re-exports |
| `src/breadmind/plugins/manifest.py` | `PluginManifest` — plugin.json 파싱/검증 |
| `src/breadmind/plugins/loader.py` | `PluginLoader` — commands/skills/agents/hooks/x-breadmind 로드 |
| `src/breadmind/plugins/manager.py` | `PluginManager` — discover/load/unload/install/uninstall |
| `src/breadmind/plugins/registry.py` | `PluginRegistry` — 설치 플러그인 인덱스 (registry.json) |
| `src/breadmind/plugins/marketplace.py` | `MarketplaceClient` — 원격 검색/설치 |
| `src/breadmind/plugins/declarative_adapter.py` | `DeclarativeAdapter` — plugin.json의 coding_agents를 CodingAgentAdapter로 변환 |
| `tests/test_plugin_system.py` | All tests |

### Modified Files
| File | Change |
|------|--------|
| `src/breadmind/core/bootstrap.py` | `PluginManager.load_all()` 호출 추가 |
| `src/breadmind/coding/adapters/__init__.py` | `register_adapter()` 동적 등록 지원 |
| `src/breadmind/web/routes/config.py` | 플러그인 API 엔드포인트 추가 |

---

## Phase 1: Plugin System Core

### Task 1: PluginManifest — plugin.json 파싱

**Files:**
- Create: `src/breadmind/plugins/__init__.py`
- Create: `src/breadmind/plugins/manifest.py`
- Test: `tests/test_plugin_system.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from pathlib import Path
from breadmind.plugins.manifest import PluginManifest

def test_parse_minimal_manifest():
    data = {"name": "test-plugin", "version": "1.0.0", "description": "Test"}
    m = PluginManifest.from_dict(data)
    assert m.name == "test-plugin"
    assert m.version == "1.0.0"

def test_parse_with_x_breadmind():
    data = {
        "name": "test", "version": "1.0.0", "description": "Test",
        "x-breadmind": {
            "coding_agents": [{"name": "aider", "cli_command": "aider", "prompt_flag": "--message"}],
            "settings": {"model": {"type": "string", "default": "gpt-4o"}}
        }
    }
    m = PluginManifest.from_dict(data)
    assert len(m.coding_agents) == 1
    assert m.coding_agents[0]["name"] == "aider"
    assert "model" in m.settings

def test_parse_missing_name_raises():
    with pytest.raises(ValueError):
        PluginManifest.from_dict({"version": "1.0.0"})

def test_from_directory(tmp_path):
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text('{"name":"test","version":"1.0.0","description":"T"}')
    m = PluginManifest.from_directory(tmp_path)
    assert m.name == "test"
```

- [ ] **Step 2: Implement PluginManifest**

```python
# src/breadmind/plugins/manifest.py
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class PluginManifest:
    name: str
    version: str
    description: str = ""
    author: str = ""
    commands_dir: str = "commands/"
    skills_dir: str = "skills/"
    agents_dir: str = "agents/"
    hooks_file: str = "hooks/"
    coding_agents: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    mcp_servers: str = ""
    requires: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    plugin_dir: Path | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict, plugin_dir: Path | None = None) -> PluginManifest:
        if "name" not in data:
            raise ValueError("plugin.json must have 'name' field")
        if "version" not in data:
            raise ValueError("plugin.json must have 'version' field")

        x = data.get("x-breadmind", {})
        return cls(
            name=data["name"],
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            commands_dir=data.get("commands", "commands/"),
            skills_dir=data.get("skills", "skills/"),
            agents_dir=data.get("agents", "agents/"),
            hooks_file=data.get("hooks", "hooks/"),
            coding_agents=x.get("coding_agents", []),
            roles=x.get("roles", []),
            tools=x.get("tools", []),
            mcp_servers=x.get("mcp_servers", ""),
            requires=x.get("requires", {}),
            settings=x.get("settings", {}),
            plugin_dir=plugin_dir,
        )

    @classmethod
    def from_directory(cls, plugin_dir: Path) -> PluginManifest:
        manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No plugin.json found at {manifest_path}")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls.from_dict(data, plugin_dir=plugin_dir)
```

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**: `feat(plugins): add PluginManifest parser`

---

### Task 2: PluginRegistry — 설치 인덱스 관리

**Files:**
- Create: `src/breadmind/plugins/registry.py`
- Test: `tests/test_plugin_system.py`

- [ ] **Step 1: Write failing test**

```python
from breadmind.plugins.registry import PluginRegistry

@pytest.mark.asyncio
async def test_registry_add_and_list(tmp_path):
    reg = PluginRegistry(tmp_path / "registry.json")
    await reg.add("test-plugin", {"version": "1.0.0", "enabled": True, "path": "/plugins/test"})
    plugins = await reg.list_all()
    assert "test-plugin" in plugins

@pytest.mark.asyncio
async def test_registry_remove(tmp_path):
    reg = PluginRegistry(tmp_path / "registry.json")
    await reg.add("test-plugin", {"version": "1.0.0", "enabled": True, "path": "/plugins/test"})
    await reg.remove("test-plugin")
    plugins = await reg.list_all()
    assert "test-plugin" not in plugins

@pytest.mark.asyncio
async def test_registry_toggle_enabled(tmp_path):
    reg = PluginRegistry(tmp_path / "registry.json")
    await reg.add("test-plugin", {"version": "1.0.0", "enabled": True, "path": "/plugins/test"})
    await reg.set_enabled("test-plugin", False)
    info = await reg.get("test-plugin")
    assert info["enabled"] is False
```

- [ ] **Step 2: Implement PluginRegistry** — JSON file-based registry with add/remove/list/get/set_enabled
- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**: `feat(plugins): add PluginRegistry for installed plugin index`

---

### Task 3: DeclarativeAdapter — 선언적 코딩 어댑터

**Files:**
- Create: `src/breadmind/plugins/declarative_adapter.py`
- Modify: `src/breadmind/coding/adapters/__init__.py` — add `register_adapter()`
- Test: `tests/test_plugin_system.py`

- [ ] **Step 1: Write failing test**

```python
from breadmind.plugins.declarative_adapter import DeclarativeAdapter

def test_declarative_adapter_build_command():
    config = {
        "name": "aider", "cli_command": "aider",
        "prompt_flag": "--message", "cwd_flag": "--cwd",
        "output_format": "text",
    }
    adapter = DeclarativeAdapter(config)
    cmd = adapter.build_command("/project", "add login")
    assert cmd[0] == "aider"
    assert "--message" in cmd
    assert "--cwd" in cmd

def test_declarative_adapter_with_session():
    config = {
        "name": "aider", "cli_command": "aider",
        "prompt_flag": "--message", "cwd_flag": "--cwd",
        "output_format": "text", "session_flag": "--session-id",
    }
    adapter = DeclarativeAdapter(config)
    cmd = adapter.build_command("/project", "continue", {"session_id": "s1"})
    assert "--session-id" in cmd
    assert "s1" in cmd

def test_register_dynamic_adapter():
    from breadmind.coding.adapters import register_adapter, get_adapter
    config = {"name": "test-agent", "cli_command": "test", "prompt_flag": "-p"}
    adapter = DeclarativeAdapter(config)
    register_adapter("test-agent", adapter)
    assert get_adapter("test-agent").name == "test-agent"
```

- [ ] **Step 2: Implement DeclarativeAdapter** — generic adapter from config dict. Implement `build_command()` and `parse_result()` using config flags.
- [ ] **Step 3: Add `register_adapter()` and `unregister_adapter()` to `coding/adapters/__init__.py`**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**: `feat(plugins): add DeclarativeAdapter for plugin-defined coding agents`

---

### Task 4: PluginLoader — 컴포넌트별 로드

**Files:**
- Create: `src/breadmind/plugins/loader.py`
- Test: `tests/test_plugin_system.py`

- [ ] **Step 1: Write failing test**

```python
from breadmind.plugins.loader import PluginLoader
from breadmind.plugins.manifest import PluginManifest

def test_load_coding_agents(tmp_path):
    # Create a plugin with coding_agents
    manifest = PluginManifest(
        name="test", version="1.0.0",
        coding_agents=[{"name": "test-cli", "cli_command": "test", "prompt_flag": "-p"}],
        plugin_dir=tmp_path,
    )
    loader = PluginLoader()
    components = loader.load(manifest)
    assert len(components.coding_agents) == 1
    assert components.coding_agents[0].name == "test-cli"

def test_load_commands(tmp_path):
    # Create commands dir with a .md file
    cmd_dir = tmp_path / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "hello.md").write_text("---\ndescription: Say hello\n---\nSay hello to the user.")
    manifest = PluginManifest(name="test", version="1.0.0", plugin_dir=tmp_path)
    loader = PluginLoader()
    components = loader.load(manifest)
    assert len(components.commands) == 1
    assert components.commands[0]["name"] == "hello"
```

- [ ] **Step 2: Implement PluginLoader**

```python
@dataclass
class LoadedComponents:
    commands: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    coding_agents: list[DeclarativeAdapter] = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)

class PluginLoader:
    def load(self, manifest: PluginManifest) -> LoadedComponents: ...
    def _load_commands(self, plugin_dir, commands_dir) -> list[dict]: ...
    def _load_skills(self, plugin_dir, skills_dir) -> list[dict]: ...
    def _load_agents(self, plugin_dir, agents_dir) -> list[dict]: ...
    def _load_hooks(self, plugin_dir, hooks_file) -> list[dict]: ...
    def _load_coding_agents(self, configs) -> list[DeclarativeAdapter]: ...
```

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**: `feat(plugins): add PluginLoader for component loading`

---

### Task 5: PluginManager — 라이프사이클 관리

**Files:**
- Create: `src/breadmind/plugins/manager.py`
- Create: `src/breadmind/plugins/__init__.py` (update exports)
- Test: `tests/test_plugin_system.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_manager_discover(tmp_path):
    # Create a plugin directory
    plugin_dir = tmp_path / "installed" / "test-plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"test-plugin","version":"1.0.0","description":"Test"}'
    )
    mgr = PluginManager(plugins_dir=tmp_path / "installed")
    manifests = await mgr.discover()
    assert len(manifests) == 1
    assert manifests[0].name == "test-plugin"

@pytest.mark.asyncio
async def test_manager_load_and_unload(tmp_path):
    plugin_dir = tmp_path / "installed" / "test-plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"test-plugin","version":"1.0.0","description":"Test"}'
    )
    mgr = PluginManager(plugins_dir=tmp_path / "installed")
    await mgr.load("test-plugin")
    assert "test-plugin" in mgr.loaded_plugins
    await mgr.unload("test-plugin")
    assert "test-plugin" not in mgr.loaded_plugins

@pytest.mark.asyncio
async def test_manager_install_from_local(tmp_path):
    # Create source plugin
    src = tmp_path / "source" / "my-plugin"
    (src / ".claude-plugin").mkdir(parents=True)
    (src / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"my-plugin","version":"1.0.0","description":"My plugin"}'
    )
    install_dir = tmp_path / "installed"
    install_dir.mkdir()
    mgr = PluginManager(plugins_dir=install_dir)
    manifest = await mgr.install(str(src))
    assert manifest.name == "my-plugin"
    assert (install_dir / "my-plugin" / ".claude-plugin" / "plugin.json").exists()
```

- [ ] **Step 2: Implement PluginManager**

Core methods: `discover()`, `load()`, `unload()`, `install()` (local copy + git clone), `uninstall()`, `load_all()`, `get_settings()`, `update_settings()`.

For `install()`:
- Local path: `shutil.copytree()`
- Git URL: `git clone` via subprocess
- `load()` after install

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**: `feat(plugins): add PluginManager with lifecycle management`

---

### Task 6: Bootstrap integration + builtin plugins

**Files:**
- Modify: `src/breadmind/core/bootstrap.py` — add PluginManager.load_all()
- Create: builtin coding-agents plugin in `src/breadmind/plugins/builtin/coding-agents/`
- Modify: `src/breadmind/coding/adapters/__init__.py` — load from plugins instead of hardcoded

- [ ] **Step 1: Create builtin coding-agents plugin**

```
src/breadmind/plugins/builtin/coding-agents/
├── .claude-plugin/
│   └── plugin.json
```

plugin.json:
```json
{
  "name": "builtin-coding-agents",
  "version": "0.2.1",
  "description": "Built-in coding agent adapters",
  "author": "breadmind",
  "x-breadmind": {
    "coding_agents": [
      {"name": "claude", "cli_command": "claude", "prompt_flag": "-p", "cwd_flag": "--cwd", "output_format": "json", "config_filename": "CLAUDE.md", "session_flag": "--resume"},
      {"name": "codex", "cli_command": "codex", "prompt_flag": "--prompt", "cwd_flag": "--cwd", "output_format": "text", "config_filename": "AGENTS.md", "session_flag": "--session"},
      {"name": "gemini", "cli_command": "gemini", "prompt_flag": "-p", "cwd_flag": "--cwd", "output_format": "json", "config_filename": "GEMINI.md", "session_flag": "--session"}
    ]
  }
}
```

- [ ] **Step 2: Add PluginManager initialization in bootstrap.py**

In `init_agent()`, after tool registration:
```python
from breadmind.plugins.manager import PluginManager
plugin_mgr = PluginManager(plugins_dir=plugins_dir, tool_registry=registry)
await plugin_mgr.load_all()
# Also load builtin plugins
builtin_dir = Path(__file__).parent.parent / "plugins" / "builtin"
if builtin_dir.exists():
    for p in builtin_dir.iterdir():
        if (p / ".claude-plugin" / "plugin.json").exists():
            await plugin_mgr.load_from_directory(p)
```

- [ ] **Step 3: Update coding adapters to support dynamic registration**

Make `_ADAPTERS` dict mutable and populated from plugins at boot instead of import time.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**: `feat(plugins): bootstrap integration and builtin coding-agents plugin`

---

### Task 7: Web API for plugins

**Files:**
- Modify: `src/breadmind/web/routes/config.py` — add plugin endpoints
- Test: `tests/test_plugin_system.py`

- [ ] **Step 1: Add plugin API endpoints**

```python
GET  /api/plugins                    # list installed
POST /api/plugins/install            # install {source: "path or git url"}
POST /api/plugins/:name/enable      # enable
POST /api/plugins/:name/disable     # disable
DELETE /api/plugins/:name           # uninstall
GET  /api/plugins/:name/settings    # get settings
POST /api/plugins/:name/settings    # update settings
```

- [ ] **Step 2: Write tests for API endpoints**
- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**: `feat(plugins): add web API for plugin management`

---

## Phase 2: Marketplace

### Task 8: MarketplaceClient

**Files:**
- Create: `src/breadmind/plugins/marketplace.py`
- Test: `tests/test_plugin_system.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_marketplace_search_mocked():
    from breadmind.plugins.marketplace import MarketplaceClient
    client = MarketplaceClient(registries=[])
    # Mock aiohttp to return test data
    results = await client.search("aider")
    # Verify search results structure

@pytest.mark.asyncio
async def test_marketplace_install_from_git(tmp_path):
    # Mock git clone
    client = MarketplaceClient(registries=[])
    # Verify install downloads to correct location
```

- [ ] **Step 2: Implement MarketplaceClient**

```python
class MarketplaceClient:
    def __init__(self, registries: list[dict] | None = None):
        self._registries = registries or []

    async def search(self, query: str, tags: list[str] = None) -> list[dict]: ...
    async def get_info(self, plugin_name: str) -> dict | None: ...
    async def install(self, plugin_name: str, target_dir: Path) -> Path: ...
    async def check_updates(self, installed: dict) -> list[dict]: ...
    async def _fetch_registry(self, url: str) -> list[dict]: ...
```

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**: `feat(plugins): add MarketplaceClient for remote plugin registry`

---

### Task 9: Marketplace web API + CLI

**Files:**
- Modify: `src/breadmind/web/routes/config.py` — marketplace endpoints
- Modify: `src/breadmind/main.py` — add `plugin` subcommand

- [ ] **Step 1: Add marketplace API endpoints**

```python
GET  /api/marketplace/search?q=...   # search remote registries
POST /api/marketplace/install/:name  # install from marketplace
```

- [ ] **Step 2: Add `breadmind plugin` CLI subcommand**

```python
plugin_parser = subparsers.add_parser("plugin", help="Plugin management")
plugin_sub = plugin_parser.add_subparsers(dest="plugin_action")
plugin_sub.add_parser("list")
plugin_sub.add_parser("install").add_argument("source")
plugin_sub.add_parser("uninstall").add_argument("name")
plugin_sub.add_parser("search").add_argument("query")
plugin_sub.add_parser("enable").add_argument("name")
plugin_sub.add_parser("disable").add_argument("name")
```

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**: `feat(plugins): add marketplace web API and CLI subcommand`

---

### Task 10: Integration test and final cleanup

- [ ] **Step 1: Full integration test** — create a test plugin, install, load, verify tools registered, unload, verify tools removed
- [ ] **Step 2: Run full test suite**: `python -m pytest tests/ -q`
- [ ] **Step 3: Commit**: `test(plugins): add integration test for full plugin lifecycle`
