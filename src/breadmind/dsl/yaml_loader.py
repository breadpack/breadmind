"""YAML → Agent 변환."""
from __future__ import annotations

from pathlib import Path

import yaml

from breadmind.sdk.agent import Agent, AgentConfig, PromptConfig, MemoryConfig, SafetyConfig


def load_agent_yaml(path: str | Path) -> Agent:
    """YAML 파일에서 Agent 인스턴스 생성."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    name = data.get("name", "BreadMind")

    # Config
    cfg_data = data.get("config", {})
    config = AgentConfig(
        provider=cfg_data.get("provider", "claude"),
        model=cfg_data.get("model", "claude-sonnet-4-6"),
        fallback_provider=cfg_data.get("fallback"),
        max_turns=cfg_data.get("max_turns", 10),
        api_key=cfg_data.get("api_key", ""),
    )

    # Prompt
    prompt_data = data.get("prompt", {})
    prompt = PromptConfig(
        persona=prompt_data.get("persona", "professional"),
        role=prompt_data.get("role"),
        language=prompt_data.get("language", "ko"),
        persona_name=prompt_data.get("persona_name", name),
        custom_instructions=prompt_data.get("custom_instructions"),
    )

    # Memory
    mem_data = data.get("memory", {})
    memory = MemoryConfig(
        working=mem_data.get("working", True),
        episodic=mem_data.get("episodic", False),
        semantic=mem_data.get("semantic", False),
        dream=mem_data.get("dream", False),
        max_messages=mem_data.get("max_messages", 50),
    )

    # Safety
    safety_data = data.get("safety", {})
    tools_data = data.get("tools", {})
    safety = SafetyConfig(
        autonomy=safety_data.get("autonomy", "confirm-destructive"),
        blocked_patterns=safety_data.get("blocked_patterns", []),
        approve_required=tools_data.get("approve_required", []),
    )

    # Tools
    tools = tools_data.get("include", []) if isinstance(tools_data, dict) else tools_data

    return Agent(
        name=name,
        config=config,
        prompt=prompt,
        memory=memory,
        tools=tools,
        safety=safety,
    )
