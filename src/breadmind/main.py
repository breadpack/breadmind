import asyncio
from breadmind.config import load_config, load_safety_config
from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.ollama import OllamaProvider
from breadmind.tools.registry import ToolRegistry
from breadmind.tools.builtin import shell_exec, web_search, file_read, file_write
from breadmind.tools.mcp_client import MCPClientManager
from breadmind.tools.registry_search import RegistrySearchEngine, RegistryConfig
from breadmind.tools.meta import create_meta_tools


def create_provider(config):
    provider_name = config.llm.default_provider
    if provider_name == "claude":
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not set, falling back to ollama")
            return OllamaProvider()
        return ClaudeProvider(api_key=api_key, default_model=config.llm.default_model)
    elif provider_name == "ollama":
        return OllamaProvider()
    else:
        return OllamaProvider()


async def run():
    config = load_config()
    safety_cfg = load_safety_config()

    provider = create_provider(config)
    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    # Register built-in tools
    for t in [shell_exec, web_search, file_read, file_write]:
        registry.register(t)

    # Initialize MCP
    mcp_manager = MCPClientManager(max_restart_attempts=config.mcp.max_restart_attempts)

    # Set up MCP tool execution callback
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

    # Register meta tools
    search_engine = RegistrySearchEngine([
        RegistryConfig(name=r.name, type=r.type, enabled=r.enabled, url=r.url)
        for r in config.mcp.registries
    ])
    meta_tools = create_meta_tools(mcp_manager, search_engine)
    for func in meta_tools.values():
        registry.register(func)

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        max_turns=config.llm.tool_call_max_turns,
    )

    builtin_count = len([t for t in registry.get_all_definitions() if registry.get_tool_source(t.name) == "builtin"])
    print("BreadMind v0.1.0 - AI Infrastructure Agent")
    print(f"  Built-in tools: {builtin_count}")
    print(f"  Meta tools: {len(meta_tools)}")
    print(f"  MCP servers: {len(config.mcp.servers)}")
    print("Type 'quit' to exit.\n")

    try:
        while True:
            try:
                user_input = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input.lower() in ("quit", "exit"):
                break

            response = await agent.handle_message(user_input, user="local", channel="cli")
            print(f"breadmind> {response}\n")
    finally:
        await mcp_manager.stop_all()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
