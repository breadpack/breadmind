from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from breadmind.llm.base import LLMMessage, LLMProvider

if TYPE_CHECKING:
    from breadmind.storage.database import Database

logger = logging.getLogger("breadmind.behavior")

_MAX_PROMPT_LENGTH = 2000

_NEGATIVE_PATTERNS = [
    "그게 아니라", "아닌데", "왜 안 해", "직접 해", "도구를 써",
    "실행해줘", "확인해봐", "안 되잖아", "다시 해", "틀렸",
]
_POSITIVE_PATTERNS = [
    "고마워", "잘했어", "좋아", "완벽", "정확해", "감사",
]


class BehaviorTracker:
    def __init__(
        self,
        provider: LLMProvider,
        get_behavior_prompt: Callable[[], str],
        set_behavior_prompt: Callable[[str], None],
        add_notification: Callable[[str], None],
        db: Database | None = None,
    ):
        self._provider = provider
        self._get_behavior_prompt = get_behavior_prompt
        self._set_behavior_prompt = set_behavior_prompt
        self._add_notification = add_notification
        self._db = db
        self._lock = asyncio.Lock()

    def _should_analyze(self, messages: list[LLMMessage]) -> bool:
        user_msgs = [m for m in messages if m.role == "user"]
        total = len(messages)
        return len(user_msgs) >= 2 and total >= 4

    def _extract_metrics(self, messages: list[LLMMessage]) -> dict[str, Any]:
        tool_calls: list[dict] = []
        tool_success = 0
        tool_failure = 0
        text_only = True
        user_messages: list[str] = []
        has_negative = False
        has_positive = False

        for msg in messages:
            if msg.role == "user" and msg.content:
                user_messages.append(msg.content[:200])
                content_lower = msg.content.lower()
                if any(p in content_lower for p in _NEGATIVE_PATTERNS):
                    has_negative = True
                if any(p in content_lower for p in _POSITIVE_PATTERNS):
                    has_positive = True

            if msg.role == "assistant" and msg.tool_calls:
                text_only = False
                for tc in msg.tool_calls:
                    tool_calls.append({"name": tc.name, "args_keys": list(tc.arguments.keys())})

            if msg.role == "tool" and msg.content:
                if "[success=True]" in msg.content:
                    tool_success += 1
                elif "[success=False]" in msg.content:
                    tool_failure += 1

        return {
            "tool_call_count": len(tool_calls),
            "tool_success_count": tool_success,
            "tool_failure_count": tool_failure,
            "text_only_response": text_only,
            "tool_calls": tool_calls,
            "user_messages": user_messages[:10],
            "negative_feedback": has_negative,
            "positive_feedback": has_positive,
        }

    def _build_analysis_prompt(self, current_prompt: str, metrics: dict) -> str:
        return (
            "You are an AI prompt engineer. Analyze the following conversation metrics "
            "and improve the behavior prompt if needed.\n\n"
            f"## Current Behavior Prompt\n```\n{current_prompt}\n```\n\n"
            f"## Conversation Metrics\n"
            f"- Tool calls: {metrics['tool_call_count']} "
            f"(success: {metrics['tool_success_count']}, fail: {metrics['tool_failure_count']})\n"
            f"- Text-only response (no tools used): {metrics['text_only_response']}\n"
            f"- Tools used: {', '.join(tc['name'] for tc in metrics['tool_calls']) or 'none'}\n"
            f"- Negative user feedback detected: {metrics['negative_feedback']}\n"
            f"- Positive user feedback detected: {metrics['positive_feedback']}\n"
            f"- User messages:\n"
            + "\n".join(f"  - {m}" for m in metrics["user_messages"])
            + "\n\n"
            "## Instructions\n"
            "If the current prompt is working well (tools used appropriately, no negative feedback), "
            "respond with exactly: NO_CHANGE\n\n"
            "If improvements are needed, respond in this exact format:\n"
            "REASON: one-line summary of what changed\n"
            "---\n"
            "The complete improved behavior prompt text\n\n"
            "Rules:\n"
            "- Keep the prompt concise (under 2000 characters)\n"
            "- Do not add system-specific tool names\n"
            "- Focus on universal behavioral patterns\n"
            "- Preserve existing rules that are working\n"
            "- Only add or modify rules that address observed issues"
        )

    def _parse_response(self, content: str) -> tuple[str | None, str | None]:
        content = content.strip()
        first_line = content.split("\n", 1)[0].strip()
        if first_line == "NO_CHANGE":
            return None, None

        if "---" not in content:
            return None, None

        parts = content.split("---", 1)
        header = parts[0].strip()
        prompt = parts[1].strip()

        reason = None
        for line in header.split("\n"):
            line = line.strip()
            if line.startswith("REASON:"):
                reason = line[len("REASON:"):].strip()
                break

        if not prompt or not reason:
            return None, None

        return reason, prompt

    async def analyze(
        self, session_id: str, messages: list[LLMMessage],
    ) -> dict | None:
        if not self._should_analyze(messages):
            return None

        async with self._lock:
            metrics = self._extract_metrics(messages)
            current_prompt = self._get_behavior_prompt()
            analysis_prompt = self._build_analysis_prompt(current_prompt, metrics)

            try:
                response = await self._provider.chat(
                    messages=[LLMMessage(role="user", content=analysis_prompt)],
                )
            except Exception:
                logger.exception("Behavior analysis LLM call failed")
                return None

            if not response.content:
                return None

            reason, new_prompt = self._parse_response(response.content)
            if reason is None or new_prompt is None:
                return None

            if len(new_prompt) > _MAX_PROMPT_LENGTH:
                logger.warning(
                    f"Behavior prompt too long ({len(new_prompt)} chars), skipping"
                )
                return None

            self._set_behavior_prompt(new_prompt)

            if self._db:
                try:
                    await self._db.set_setting("behavior_prompt", {
                        "prompt": new_prompt,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "reason": reason,
                    })
                except Exception:
                    logger.exception("Failed to persist behavior prompt")

            self._add_notification(
                f"[BreadMind] 행동 프롬프트가 개선되었습니다: {reason}"
            )

            logger.info(f"Behavior prompt improved: {reason}")
            return {"reason": reason, "prompt": new_prompt}
