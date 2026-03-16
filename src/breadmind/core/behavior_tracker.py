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
    "질문하지 말고", "물어보지 말고", "묻지 말고", "그냥 해",
    "알아서 해", "스스로 해", "왜 물어봐",
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
        on_prompt_updated: Callable[[str, str], Any] | None = None,
    ):
        self._provider = provider
        self._get_behavior_prompt = get_behavior_prompt
        self._set_behavior_prompt = set_behavior_prompt
        self._add_notification = add_notification
        self._db = db
        self._on_prompt_updated = on_prompt_updated
        self._lock = asyncio.Lock()
        self._prompt_versions: list[dict] = []
        self._current_version: int = 0
        self._effectiveness: dict[int, list[float]] = {}

    def _should_analyze(self, messages: list[LLMMessage]) -> bool:
        user_msgs = [m for m in messages if m.role == "user"]
        tool_msgs = [m for m in messages if m.role == "tool"]
        has_negative = any(
            any(p in (m.content or "").lower() for p in _NEGATIVE_PATTERNS)
            for m in messages if m.role == "user" and m.content
        )
        # Analyze if: multi-turn conversation OR meaningful single-turn with tools
        # OR negative feedback detected (always worth analyzing)
        if has_negative:
            return True
        if len(user_msgs) >= 2:
            return True
        # Single user message but had tool interactions (typical BreadMind usage)
        if len(user_msgs) >= 1 and len(tool_msgs) >= 1:
            return True
        return False

    def _extract_metrics(self, messages: list[LLMMessage]) -> dict[str, Any]:
        tool_calls: list[dict] = []
        tool_success = 0
        tool_failure = 0
        text_only = True
        user_messages: list[str] = []
        assistant_messages: list[str] = []
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

            if msg.role == "assistant":
                if msg.content:
                    assistant_messages.append(msg.content[:200])
                if msg.tool_calls:
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
            "assistant_messages": assistant_messages[:10],
            "negative_feedback": has_negative,
            "positive_feedback": has_positive,
        }

    def _build_analysis_prompt(self, current_prompt: str, metrics: dict) -> str:
        assistant_section = ""
        if metrics.get("assistant_messages"):
            assistant_section = (
                f"- Agent responses:\n"
                + "\n".join(f"  - {m}" for m in metrics["assistant_messages"])
                + "\n"
            )

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
            + "\n"
            + assistant_section
            + "\n"
            "## Instructions\n"
            "Analyze whether the agent behaved optimally. Look for these anti-patterns:\n"
            "- Agent asked unnecessary clarifying questions instead of investigating with tools\n"
            "- Agent gave text-only advice instead of executing actions\n"
            "- Agent asked for confirmation on non-destructive operations\n"
            "- Agent failed to use available tools when they could have answered the question\n\n"
            "If the current prompt is working well AND no anti-patterns detected, "
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
            "- Only add or modify rules that address observed issues\n"
            "- CRITICAL: Always preserve the 'Autonomous Problem Solving' section. "
            "The agent must solve problems autonomously and only ask users when "
            "tool-based investigation is exhausted and the decision genuinely requires user input."
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
                logger.debug("Behavior analysis result: NO_CHANGE")
                return None

            if len(new_prompt) > _MAX_PROMPT_LENGTH:
                logger.warning(
                    f"Behavior prompt too long ({len(new_prompt)} chars), skipping"
                )
                return None

            self._set_behavior_prompt(new_prompt)

            self._current_version += 1
            self._prompt_versions.append({
                "version": self._current_version,
                "prompt": new_prompt,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metrics_snapshot": {
                    "tool_success_rate": (
                        metrics["tool_success_count"] /
                        max(metrics["tool_call_count"], 1)
                    ),
                    "text_only": metrics["text_only_response"],
                    "negative_feedback": metrics["negative_feedback"],
                },
            })
            # Keep last 20 versions
            if len(self._prompt_versions) > 20:
                self._prompt_versions = self._prompt_versions[-20:]

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

            # Notify UI via broadcast callback
            if self._on_prompt_updated is not None:
                try:
                    result = self._on_prompt_updated(new_prompt, reason)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Failed to broadcast behavior prompt update")

            logger.info(f"Behavior prompt improved: {reason}")
            return {"reason": reason, "prompt": new_prompt}

    def record_effectiveness(self, success_rate: float, text_only: bool):
        """Record effectiveness of current prompt version."""
        ver = self._current_version
        if ver not in self._effectiveness:
            self._effectiveness[ver] = []
        self._effectiveness[ver].append(1.0 if not text_only else 0.0)

    def get_version_history(self) -> list[dict]:
        """Return prompt version history with effectiveness scores."""
        result = []
        for v in self._prompt_versions:
            ver = v["version"]
            scores = self._effectiveness.get(ver, [])
            avg = sum(scores) / len(scores) if scores else None
            result.append({**v, "avg_effectiveness": avg, "sample_count": len(scores)})
        return result
