"""v2 SDK Agent: 최소 5줄로 에이전트 생성."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from breadmind.core.protocols import AgentContext, PromptContext


@dataclass
class AgentConfig:
    provider: str = "claude"
    model: str = "claude-sonnet-4-6"
    fallback_provider: str | None = None
    max_turns: int = 10
    api_key: str = ""


@dataclass
class PromptConfig:
    persona: str = "professional"
    role: str | None = None
    language: str = "ko"
    persona_name: str = "BreadMind"
    custom_instructions: str | None = None


@dataclass
class MemoryConfig:
    working: bool = True
    episodic: bool = False
    semantic: bool = False
    dream: bool = False
    max_messages: int = 50
    compress_threshold: int = 30


@dataclass
class SafetyConfig:
    autonomy: str = "confirm-destructive"
    blocked_patterns: list[str] = field(default_factory=list)
    approve_required: list[str] = field(default_factory=list)


class Agent:
    """v2 SDK 에이전트. 최소 설정으로 동작."""

    def __init__(
        self,
        name: str = "BreadMind",
        config: AgentConfig | None = None,
        prompt: PromptConfig | None = None,
        memory: MemoryConfig | None = None,
        tools: list[str] | list[Any] | None = None,
        safety: SafetyConfig | None = None,
        plugins: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.config = config or AgentConfig()
        self.prompt = prompt or PromptConfig()
        self.memory_config = memory or MemoryConfig()
        self.safety_config = safety or SafetyConfig()
        self.tools = tools or []
        self.plugins = plugins or {}
        self._agent_loop: Any = None
        self._initialized = False

    def _build(self) -> None:
        """Lazy initialization of internal components."""
        if self._initialized:
            return

        from breadmind.core.logging import setup_logging
        setup_logging()

        from breadmind.plugins.builtin.safety.guard import SafetyGuard

        # Safety
        self._safety = SafetyGuard(
            autonomy=self.safety_config.autonomy,
            blocked_patterns=self.safety_config.blocked_patterns,
            approve_required=self.safety_config.approve_required,
        )

        # Memory
        self._working_memory = None
        if self.memory_config.working:
            from breadmind.plugins.builtin.memory.working_memory import WorkingMemory
            self._working_memory = WorkingMemory(
                max_messages=self.memory_config.max_messages,
                compress_threshold=self.memory_config.compress_threshold,
            )

        # Prompt context
        self._prompt_context = PromptContext(
            persona_name=self.prompt.persona_name or self.name,
            language=self.prompt.language,
            custom_instructions=self.prompt.custom_instructions,
            role=self.prompt.role,
            persona=self.prompt.persona,
        )

        self._initialized = True

    async def run(self, message: str, user: str = "sdk_user", channel: str = "sdk") -> str:
        """단일 메시지 처리. 간단한 사용을 위한 메서드."""
        self._build()

        # Use plugins override or create default components
        provider = self.plugins.get("provider")
        prompt_builder = self.plugins.get("prompt_builder")
        tool_registry = self.plugins.get("tool_registry")

        if provider is None:
            raise ValueError(
                "Provider not configured. Pass provider via plugins={'provider': your_provider} "
                "or set config.api_key for auto-configuration."
            )

        if prompt_builder is None:
            # Minimal prompt builder
            from breadmind.core.protocols import PromptBlock

            class MinimalPromptBuilder:
                def build(self, ctx):
                    return [PromptBlock(section="identity", content=f"You are {ctx.persona_name}.", cacheable=True, priority=1)]
            prompt_builder = MinimalPromptBuilder()

        if tool_registry is None:
            from breadmind.plugins.builtin.tools.registry import HybridToolRegistry
            tool_registry = HybridToolRegistry()

        from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
        agent = MessageLoopAgent(
            provider=provider,
            prompt_builder=prompt_builder,
            tool_registry=tool_registry,
            safety_guard=self._safety,
            max_turns=self.config.max_turns,
            prompt_context=self._prompt_context,
        )

        ctx = AgentContext(user=user, channel=channel, session_id=f"{user}:{channel}")
        response = await agent.handle_message(message, ctx)
        return response.content

    async def serve(self, runtime: str = "cli", **kwargs: Any) -> None:
        """런타임 실행. CLI 또는 서버 모드."""
        self._build()
        if runtime == "cli":
            from breadmind.plugins.builtin.runtimes.cli_runtime import CLIRuntime
            rt = CLIRuntime(agent=self)
            await rt.start(container=None)
        elif runtime == "server":
            from breadmind.plugins.builtin.runtimes.server_runtime import ServerRuntime
            rt = ServerRuntime(agent=self, **kwargs)
            await rt.start(container=None)
        else:
            raise ValueError(f"Unknown runtime: {runtime}")

    @classmethod
    def from_yaml(cls, path: str) -> "Agent":
        """YAML 파일에서 Agent 생성."""
        from breadmind.dsl.yaml_loader import load_agent_yaml
        return load_agent_yaml(path)
