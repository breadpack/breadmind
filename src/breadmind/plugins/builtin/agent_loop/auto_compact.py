"""Auto-compact: context window 초과 방지를 위한 대화 자동 압축."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from breadmind.core.protocols import Message, ProviderProtocol

logger = logging.getLogger(__name__)


@dataclass
class CompactConfig:
    """Auto-compact 설정."""
    max_context_tokens: int = 100_000   # context window budget
    compact_threshold: float = 0.7      # 70% 도달 시 compact 트리거
    keep_recent: int = 6                # 최근 N개 메시지 유지
    summary_max_tokens: int = 2000      # 요약 최대 토큰


class AutoCompactor:
    """매 turn마다 context window 사용량을 체크하고, threshold 초과 시 오래된 메시지를 요약하여 압축."""

    def __init__(
        self,
        provider: ProviderProtocol,
        config: CompactConfig | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or CompactConfig()

    def estimate_tokens(self, messages: list[Message]) -> int:
        """간단한 토큰 추정 (문자수 / 4)."""
        total = 0
        for msg in messages:
            total += len(msg.content or "") // 4
        return total

    def should_compact(self, messages: list[Message]) -> bool:
        """현재 토큰이 threshold 초과하는지 확인."""
        tokens = self.estimate_tokens(messages)
        limit = int(self._config.max_context_tokens * self._config.compact_threshold)
        return tokens > limit

    async def compact(self, messages: list[Message]) -> list[Message]:
        """오래된 메시지를 요약하고 최근 메시지만 유지.

        결과: [system_msg, summary_msg, ...recent_msgs]
        - system_msg: 기존 첫 system 메시지 (있으면)
        - summary_msg: Message(role="system", content="[Previous conversation summary] ...")
        - recent_msgs: keep_recent개의 최근 메시지
        """
        keep = self._config.keep_recent

        # 메시지가 충분하지 않으면 압축 불필요
        if len(messages) <= keep + 1:
            return messages

        # 첫 system 메시지 분리
        system_msg: Message | None = None
        start_idx = 0
        if messages and messages[0].role == "system":
            system_msg = messages[0]
            start_idx = 1

        # 최근 메시지 분리
        recent = messages[-keep:]
        old = messages[start_idx:-keep] if len(messages) > start_idx + keep else []

        if not old:
            return messages

        # LLM으로 요약 생성
        try:
            summary_text = await self._summarize(old)
        except Exception:
            logger.exception("Auto-compact summarization failed, keeping original messages")
            return messages

        summary_msg = Message(
            role="system",
            content=f"[Previous conversation summary] {summary_text}",
        )

        result: list[Message] = []
        if system_msg is not None:
            result.append(system_msg)
        result.append(summary_msg)
        result.extend(recent)

        old_tokens = self.estimate_tokens(messages)
        new_tokens = self.estimate_tokens(result)
        logger.info(
            "Auto-compact: %d tokens -> %d tokens (saved %d)",
            old_tokens, new_tokens, old_tokens - new_tokens,
        )

        return result

    async def _summarize(self, messages: list[Message]) -> str:
        """메시지 목록을 LLM으로 요약."""
        conversation = "\n".join(
            f"[{m.role}]: {m.content or '(empty)'}" for m in messages
        )
        prompt_messages = [
            Message(
                role="system",
                content=(
                    "Summarize the following conversation concisely. "
                    "Preserve key decisions, actions taken, and results. "
                    "Keep technical details (commands, paths, error messages). "
                    "Output a brief summary paragraph."
                ),
            ),
            Message(role="user", content=conversation),
        ]
        response = await self._provider.chat(messages=prompt_messages)
        return response.content or "Unable to summarize."
