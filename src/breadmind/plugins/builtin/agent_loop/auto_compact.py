"""Auto-compact: context window 초과 방지를 위한 다단계 대화 자동 압축."""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

from breadmind.core.protocols import Message, ProviderProtocol

if TYPE_CHECKING:
    from breadmind.core.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class CompactionLevel(IntEnum):
    """압축 단계."""
    NONE = 0
    TOOL_RESULT_TRIM = 1    # Trim large tool results (>5000 chars) to preview
    SNIP_OLD_RESULTS = 2    # Replace old tool results with "[content cleared]"
    SUMMARIZE_OLD = 3       # LLM-summarize old messages, keep recent
    AGGRESSIVE_COMPACT = 4  # Summarize everything except system + last 4 messages


@dataclass
class CompactConfig:
    """Auto-compact 설정."""
    max_context_tokens: int = 100_000
    level_thresholds: dict[int, float] = field(default_factory=lambda: {
        1: 0.5,
        2: 0.65,
        3: 0.75,
        4: 0.9,
    })
    tool_result_preview_size: int = 500
    keep_recent: int = 6
    summary_max_tokens: int = 2000
    preserve_system: bool = True

    # backward compat
    compact_threshold: float = 0.7


class AutoCompactor:
    """매 turn마다 context window 사용량을 체크하고, 다단계 압축을 수행."""

    def __init__(
        self,
        provider: ProviderProtocol,
        config: CompactConfig | None = None,
        token_counter: TokenCounter | None = None,
        instruction_files: list[str] | None = None,
        on_pre_compact: Callable | None = None,
        on_post_compact: Callable | None = None,
        compact_instructions: str | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or CompactConfig()
        self._token_counter = token_counter
        self._instruction_files = instruction_files or []
        self._on_pre_compact = on_pre_compact
        self._on_post_compact = on_post_compact
        self._compact_instructions = compact_instructions
        self._last_compact_level: CompactionLevel = CompactionLevel.NONE

    @property
    def last_compact_level(self) -> CompactionLevel:
        """마지막 compact() 호출에서 사용된 압축 레벨."""
        return self._last_compact_level

    def estimate_tokens(self, messages: list[Message]) -> int:
        """토큰 수 추정. TokenCounter가 있으면 정확한 카운팅, 없으면 문자수/4 fallback."""
        if self._token_counter is not None:
            return self._token_counter.count_messages(messages)
        total = 0
        for msg in messages:
            total += len(msg.content or "") // 4
        return total

    def determine_level(self, messages: list[Message]) -> CompactionLevel:
        """현재 토큰 사용량을 기반으로 필요한 압축 레벨 결정."""
        tokens = self.estimate_tokens(messages)
        max_tokens = self._config.max_context_tokens
        thresholds = self._config.level_thresholds

        determined = CompactionLevel.NONE
        for level in sorted(thresholds.keys()):
            threshold_tokens = int(max_tokens * thresholds[level])
            if tokens > threshold_tokens:
                determined = CompactionLevel(level)
        return determined

    def should_compact(self, messages: list[Message]) -> bool:
        """현재 토큰이 어떤 압축 레벨이든 필요한지 확인 (하위 호환)."""
        return self.determine_level(messages) > CompactionLevel.NONE

    async def compact(
        self,
        messages: list[Message],
        force_level: CompactionLevel | None = None,
    ) -> list[Message]:
        """다단계 압축 수행.

        각 레벨은 이전 레벨의 변환을 포함한다.
        결과와 사용된 레벨을 반환. 하위 호환을 위해 list[Message]를 반환하며,
        사용된 레벨은 self._last_compact_level에 저장.
        """
        level = force_level if force_level is not None else self.determine_level(messages)
        self._last_compact_level = level

        if level == CompactionLevel.NONE:
            return messages

        # Fire pre-compact hook
        if self._on_pre_compact:
            try:
                if asyncio.iscoroutinefunction(self._on_pre_compact):
                    await self._on_pre_compact(messages, level)
                else:
                    self._on_pre_compact(messages, level)
            except Exception:
                logger.warning("Pre-compact hook failed", exc_info=True)

        result = list(messages)

        # Level 1: Trim large tool results
        if level >= CompactionLevel.TOOL_RESULT_TRIM:
            result = self._trim_tool_results(result)

        # Level 2: Snip old tool results
        if level >= CompactionLevel.SNIP_OLD_RESULTS:
            result = self._snip_old_results(result)

        # Level 3: Summarize old messages
        if level >= CompactionLevel.SUMMARIZE_OLD:
            try:
                result = await self._summarize_old(result)
            except Exception:
                logger.exception("Auto-compact summarization failed at level 3")
                return messages

        # Level 4: Aggressive compact
        if level >= CompactionLevel.AGGRESSIVE_COMPACT:
            try:
                result = await self._aggressive_compact(result)
            except Exception:
                logger.exception("Auto-compact failed at level 4")
                return messages

        # Re-inject instruction files (they must survive compaction)
        if self._instruction_files and result:
            injected = []
            for fpath in self._instruction_files:
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        injected.append(Message(
                            role="system",
                            content=f"[Instruction file: {os.path.basename(fpath)}]\n{content}",
                        ))
                except (IOError, OSError):
                    pass
            if injected:
                # Insert after system message but before conversation
                insert_idx = 1 if result and result[0].role == "system" else 0
                for i, msg in enumerate(injected):
                    result.insert(insert_idx + i, msg)

        old_tokens = self.estimate_tokens(messages)
        new_tokens = self.estimate_tokens(result)
        logger.info(
            "Auto-compact level %d: %d tokens -> %d tokens (saved %d)",
            level, old_tokens, new_tokens, old_tokens - new_tokens,
        )

        # Fire post-compact hook
        if self._on_post_compact:
            try:
                if asyncio.iscoroutinefunction(self._on_post_compact):
                    await self._on_post_compact(result, level)
                else:
                    self._on_post_compact(result, level)
            except Exception:
                logger.warning("Post-compact hook failed", exc_info=True)

        return result

    def _trim_tool_results(self, messages: list[Message]) -> list[Message]:
        """Level 1: 5000자 이상의 tool result를 preview 크기로 자른다."""
        preview_size = self._config.tool_result_preview_size
        result = []
        for msg in messages:
            if msg.role == "tool" and msg.content and len(msg.content) > 5000:
                trimmed = Message(
                    role=msg.role,
                    content=msg.content[:preview_size] + "\n[...trimmed]",
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                    is_meta=msg.is_meta,
                )
                result.append(trimmed)
            else:
                result.append(msg)
        return result

    def _snip_old_results(self, messages: list[Message]) -> list[Message]:
        """Level 2: keep_recent 이전의 tool result 내용을 제거한다."""
        keep = self._config.keep_recent
        if len(messages) <= keep:
            return messages

        boundary = len(messages) - keep
        result = []
        for i, msg in enumerate(messages):
            if i < boundary and msg.role == "tool":
                snipped = Message(
                    role=msg.role,
                    content="[Old tool result content cleared]",
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                    is_meta=msg.is_meta,
                )
                result.append(snipped)
            else:
                result.append(msg)
        return result

    async def _summarize_old(self, messages: list[Message]) -> list[Message]:
        """Level 3: 오래된 메시지를 LLM으로 요약하고 최근 메시지만 유지."""
        keep = self._config.keep_recent

        if len(messages) <= keep + 1:
            return messages

        # 첫 system 메시지 분리
        system_msg: Message | None = None
        start_idx = 0
        if self._config.preserve_system and messages and messages[0].role == "system":
            system_msg = messages[0]
            start_idx = 1

        recent = messages[-keep:]
        old = messages[start_idx:-keep] if len(messages) > start_idx + keep else []

        if not old:
            return messages

        summary_text = await self._summarize(old)

        summary_msg = Message(
            role="system",
            content=f"[Previous conversation summary] {summary_text}",
        )

        result: list[Message] = []
        if system_msg is not None:
            result.append(system_msg)
        result.append(summary_msg)
        result.extend(recent)
        return result

    async def _aggressive_compact(self, messages: list[Message]) -> list[Message]:
        """Level 4: 모든 것을 요약하고, system + 마지막 4개 메시지만 유지."""
        aggressive_keep = 4

        # system 메시지 분리
        system_msg: Message | None = None
        start_idx = 0
        if self._config.preserve_system and messages and messages[0].role == "system":
            system_msg = messages[0]
            start_idx = 1

        # 이미 충분히 적으면 그대로
        if len(messages) <= aggressive_keep + (1 if system_msg else 0):
            return messages

        recent = messages[-aggressive_keep:]
        old = messages[start_idx:-aggressive_keep] if len(messages) > start_idx + aggressive_keep else []

        if not old:
            return messages

        summary_text = await self._summarize(old)

        summary_msg = Message(
            role="system",
            content=f"[Aggressively compacted summary] {summary_text}",
        )

        result: list[Message] = []
        if system_msg is not None:
            result.append(system_msg)
        result.append(summary_msg)
        result.extend(recent)
        return result

    async def _summarize(self, messages: list[Message]) -> str:
        """메시지 목록을 LLM으로 요약."""
        conversation = "\n".join(
            f"[{m.role}]: {m.content or '(empty)'}" for m in messages
        )
        system_content = (
            "Summarize the following conversation concisely. "
            "Preserve key decisions, actions taken, and results. "
            "Keep technical details (commands, paths, error messages). "
            "Output a brief summary paragraph."
        )
        if self._compact_instructions:
            system_content += f"\n\nAdditional instructions: {self._compact_instructions}"
        prompt_messages = [
            Message(role="system", content=system_content),
            Message(role="user", content=conversation),
        ]
        response = await self._provider.chat(messages=prompt_messages)
        return response.content or "Unable to summarize."
