"""ReminderInjector for provider-aware context injection."""
from __future__ import annotations
from breadmind.core.protocols import Message, ProviderProtocol


class ReminderInjector:
    """프로바이더에 맞게 대화 중간 컨텍스트를 주입."""

    def inject(self, key: str, content: str, provider: ProviderProtocol) -> Message:
        """
        인젝트 메시지를 생성하여 프로바이더의 지원 기능에 따라 포맷을 결정.

        Args:
            key: 컨텍스트 키 (예: "memory", "config")
            content: 주입할 컨텍스트 내용
            provider: LLM 프로바이더

        Returns:
            생성된 메시지 객체
        """
        if provider.supports_feature("system_reminder"):
            return Message(
                role="user",
                content=f"<system-reminder>\n# {key}\n{content}\n</system-reminder>",
                is_meta=True,
            )
        return Message(
            role="system",
            content=f"[Context: {key}]\n{content}",
            is_meta=True,
        )
