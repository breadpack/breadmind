"""Pluggable Context Engine — lifecycle-based context management.

OpenClaw-inspired design with 7 lifecycle hooks that allow swapping
context strategies without modifying core agent code.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ContextPhase(str, Enum):
    BOOTSTRAP = "bootstrap"
    INGEST = "ingest"
    ASSEMBLE = "assemble"
    COMPACT = "compact"
    AFTER_TURN = "after_turn"
    PREPARE_SUBAGENT = "prepare_subagent"
    ON_SUBAGENT_ENDED = "on_subagent_ended"


@dataclass
class ContextState:
    messages: list[dict] = field(default_factory=list)
    system_prompt: str = ""
    tools: list[dict] = field(default_factory=list)
    token_count: int = 0
    max_tokens: int = 200_000
    metadata: dict = field(default_factory=dict)

    @property
    def usage_ratio(self) -> float:
        if self.max_tokens == 0:
            return 0.0
        return self.token_count / self.max_tokens


@dataclass
class ContextEngineConfig:
    max_tokens: int = 200_000
    compact_threshold: float = 0.75
    target_after_compact: float = 0.50
    preserve_recent_turns: int = 5


class ContextEngine(ABC):
    """Abstract context engine with 7 lifecycle phases.

    Implementations can provide different strategies for context management
    (e.g., aggressive compaction, lossless DAG-based, sliding window, etc.)
    """

    def __init__(self, config: ContextEngineConfig | None = None):
        self._config = config or ContextEngineConfig()
        self._state = ContextState(max_tokens=self._config.max_tokens)

    @property
    def state(self) -> ContextState:
        return self._state

    @abstractmethod
    def bootstrap(
        self, system_prompt: str, tools: list[dict], instructions: str = "",
    ) -> ContextState:
        """Phase 1: Initialize context with system prompt, tools, instructions."""
        ...

    @abstractmethod
    def ingest(self, message: dict) -> ContextState:
        """Phase 2: Process a new message (user, assistant, tool_result)."""
        ...

    @abstractmethod
    def assemble(self) -> list[dict]:
        """Phase 3: Build the final message list for LLM API call."""
        ...

    @abstractmethod
    def compact(self) -> ContextState:
        """Phase 4: Compress context when approaching token limit."""
        ...

    @abstractmethod
    def after_turn(self, assistant_message: dict) -> None:
        """Phase 5: Post-turn cleanup and bookkeeping."""
        ...

    def prepare_subagent(self, task: str) -> ContextState:
        """Phase 6: Prepare minimal context for a subagent."""
        sub_state = ContextState(
            system_prompt=self._state.system_prompt,
            tools=list(self._state.tools),
            max_tokens=self._config.max_tokens,
            metadata={"parent_task": task},
        )
        sub_state.messages = [{"role": "user", "content": task}]
        sub_state.token_count = self._estimate_tokens(task)
        return sub_state

    def on_subagent_ended(self, result: dict) -> None:
        """Phase 7: Merge subagent results back into main context."""
        summary = result.get("summary", "")
        if summary:
            self._state.messages.append(
                {"role": "assistant", "content": f"[subagent result] {summary}"}
            )
            self._state.token_count += self._estimate_tokens(summary)

    def needs_compaction(self) -> bool:
        return self._state.usage_ratio >= self._config.compact_threshold

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token."""
        return max(1, len(text) // 4)


class DefaultContextEngine(ContextEngine):
    """Default implementation: sliding window with simple truncation."""

    def bootstrap(
        self, system_prompt: str, tools: list[dict], instructions: str = "",
    ) -> ContextState:
        full_prompt = system_prompt
        if instructions:
            full_prompt = f"{system_prompt}\n\n{instructions}"
        self._state.system_prompt = full_prompt
        self._state.tools = list(tools)
        self._state.messages = []
        self._state.token_count = self._estimate_tokens(full_prompt)
        return self._state

    def ingest(self, message: dict) -> ContextState:
        self._state.messages.append(message)
        content = message.get("content", "")
        if isinstance(content, str):
            self._state.token_count += self._estimate_tokens(content)
        return self._state

    def assemble(self) -> list[dict]:
        return list(self._state.messages)

    def compact(self) -> ContextState:
        """Truncate oldest messages, preserving recent turns."""
        preserve = self._config.preserve_recent_turns * 2  # user+assistant pairs
        messages = self._state.messages

        if len(messages) <= preserve:
            return self._state

        self._state.messages = messages[-preserve:]
        # Recalculate token count
        total = self._estimate_tokens(self._state.system_prompt)
        for msg in self._state.messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self._estimate_tokens(content)
        self._state.token_count = total
        return self._state

    def after_turn(self, assistant_message: dict) -> None:
        """No special post-turn processing in default engine."""
        pass


class LosslessContextEngine(ContextEngine):
    """Lossless strategy: summarize old turns but preserve all decisions/facts.

    Inspired by OpenClaw's DAG-based approach.
    """

    def __init__(
        self,
        config: ContextEngineConfig | None = None,
        summarizer=None,
    ):
        super().__init__(config)
        self._summarizer = summarizer  # callable(messages) -> summary str
        self._summaries: list[str] = []

    def bootstrap(
        self, system_prompt: str, tools: list[dict], instructions: str = "",
    ) -> ContextState:
        full_prompt = system_prompt
        if instructions:
            full_prompt = f"{system_prompt}\n\n{instructions}"
        self._state.system_prompt = full_prompt
        self._state.tools = list(tools)
        self._state.messages = []
        self._summaries = []
        self._state.token_count = self._estimate_tokens(full_prompt)
        return self._state

    def ingest(self, message: dict) -> ContextState:
        self._state.messages.append(message)
        content = message.get("content", "")
        if isinstance(content, str):
            self._state.token_count += self._estimate_tokens(content)
        return self._state

    def assemble(self) -> list[dict]:
        """Build message list with summaries prepended as context."""
        result: list[dict] = []
        if self._summaries:
            summary_text = "\n---\n".join(self._summaries)
            result.append(
                {"role": "user", "content": f"[Previous context summary]\n{summary_text}"}
            )
            result.append(
                {"role": "assistant", "content": "Understood, I have the previous context."}
            )
        result.extend(self._state.messages)
        return result

    def compact(self) -> ContextState:
        """Summarize old turns, keeping summaries + recent turns."""
        preserve = self._config.preserve_recent_turns * 2
        messages = self._state.messages

        if len(messages) <= preserve:
            return self._state

        old_messages = messages[:-preserve]
        recent_messages = messages[-preserve:]

        # Generate summary of old messages
        if self._summarizer is not None:
            summary = self._summarizer(old_messages)
        else:
            summary = self._default_summarize(old_messages)

        self._summaries.append(summary)
        self._state.messages = recent_messages

        # Recalculate token count
        total = self._estimate_tokens(self._state.system_prompt)
        for s in self._summaries:
            total += self._estimate_tokens(s)
        for msg in self._state.messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self._estimate_tokens(content)
        self._state.token_count = total
        return self._state

    def after_turn(self, assistant_message: dict) -> None:
        """Track decisions and facts from assistant responses."""
        pass

    @staticmethod
    def _default_summarize(messages: list[dict]) -> str:
        """Simple extractive summary: collect first line of each message."""
        lines: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                first_line = content.strip().split("\n")[0][:200]
                role = msg.get("role", "unknown")
                lines.append(f"[{role}] {first_line}")
        return "\n".join(lines) if lines else "(no content)"


class ContextEngineRegistry:
    """Registry for context engine implementations."""

    _engines: dict[str, type[ContextEngine]] = {}

    @classmethod
    def register(cls, name: str, engine_cls: type[ContextEngine]) -> None:
        cls._engines[name] = engine_cls

    @classmethod
    def create(
        cls, name: str, config: ContextEngineConfig | None = None, **kwargs,
    ) -> ContextEngine:
        if name not in cls._engines:
            raise KeyError(f"Unknown context engine: {name!r}. Available: {cls.list_engines()}")
        return cls._engines[name](config=config, **kwargs)

    @classmethod
    def list_engines(cls) -> list[str]:
        return sorted(cls._engines.keys())


# Register defaults
ContextEngineRegistry.register("default", DefaultContextEngine)
ContextEngineRegistry.register("lossless", LosslessContextEngine)
