"""Conversation Compressor — summarizes old messages to preserve context.

Instead of dropping old messages when the history exceeds max_messages,
compresses them into a summary that retains key decisions, requirements,
and context while reducing token count.
"""
from __future__ import annotations

import logging
from typing import Any

from breadmind.constants import THINK_BUDGET_SMALL
from breadmind.llm.base import LLMMessage

logger = logging.getLogger("breadmind.memory.compressor")

# Tool result messages often contain large outputs that dominate context
TOOL_RESULT_MAX_LENGTH = 300

COMPRESSION_PROMPT = """\
Summarize the following conversation history concisely in Korean.
Preserve ALL of the following:
- User's original requirements and goals
- Architecture decisions made
- Key technical constraints agreed upon
- Tool calls made and their outcomes (success/failure, not full output)
- Current project state and progress
- Any pending tasks or next steps discussed

Do NOT include:
- Full tool output text
- Repetitive error messages
- System prompts or approval IDs

Format as a structured summary with clear sections.
Keep under 800 tokens."""


def truncate_tool_results(messages: list[LLMMessage]) -> list[LLMMessage]:
    """Truncate tool result messages to reduce token usage."""
    result = []
    for msg in messages:
        if msg.role == "tool" and msg.content and len(msg.content) > TOOL_RESULT_MAX_LENGTH:
            # Extract success/failure status and truncate
            content = msg.content
            if "[success=True]" in content:
                status = "[success=True]"
            elif "[success=False]" in content:
                status = "[success=False]"
            else:
                status = ""
            truncated = f"{status} {content[:TOOL_RESULT_MAX_LENGTH]}... [truncated]"
            result.append(LLMMessage(
                role=msg.role, content=truncated,
                tool_call_id=getattr(msg, "tool_call_id", None),
                name=getattr(msg, "name", None),
            ))
        elif msg.role == "user" and msg.content and msg.content.startswith("[System] Tool"):
            # System tool result forwarded as user message — truncate
            content = msg.content
            if len(content) > TOOL_RESULT_MAX_LENGTH:
                result.append(LLMMessage(
                    role=msg.role,
                    content=content[:TOOL_RESULT_MAX_LENGTH] + "... [truncated]",
                ))
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result


async def compress_history(
    messages: list[LLMMessage],
    provider: Any,
    keep_recent: int = 10,
) -> list[LLMMessage]:
    """Compress old messages into a summary, keeping recent ones intact.

    Args:
        messages: Full message list
        provider: LLM provider for generating summary
        keep_recent: Number of recent messages to keep verbatim

    Returns:
        New message list: [summary_msg] + recent_messages
    """
    # ─ PRE_COMPACT hook wiring ─
    from breadmind.core.events import get_event_bus
    from breadmind.hooks import HookEvent, HookPayload

    decision = await get_event_bus().run_hook_chain(
        HookEvent.PRE_COMPACT,
        HookPayload(
            event=HookEvent.PRE_COMPACT,
            data={
                "messages_count": len(messages),
                "keep_recent": keep_recent,
                "messages": list(messages),
            },
        ),
    )
    kind_value = getattr(getattr(decision, "kind", None), "value", "proceed")
    if kind_value == "block":
        return list(messages)  # skip compaction, return original
    if kind_value == "modify":
        patch = getattr(decision, "patch", None) or {}
        if "messages" in patch:
            messages = list(patch["messages"])
    # ─ end hook wiring ─

    if len(messages) <= keep_recent:
        return messages

    # Split: old messages to summarize, recent to keep
    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    # Check if there's already a summary at the start
    existing_summary = ""
    if old_messages and old_messages[0].role == "system" and "[대화 요약]" in (old_messages[0].content or ""):
        existing_summary = old_messages[0].content
        old_messages = old_messages[1:]

    if not old_messages:
        return messages

    # Build text to summarize
    lines = []
    if existing_summary:
        lines.append(f"이전 요약:\n{existing_summary}\n")
    lines.append("추가 대화:")
    for msg in old_messages:
        role = {"user": "사용자", "assistant": "BreadMind", "tool": "도구결과", "system": "시스템"}.get(msg.role, msg.role)
        content = msg.content or ""
        # Truncate long content for summarization input
        if len(content) > 500:
            content = content[:500] + "..."
        name = getattr(msg, "name", None)
        if name:
            lines.append(f"[{role}/{name}] {content}")
        else:
            lines.append(f"[{role}] {content}")

    text_to_summarize = "\n".join(lines)

    # Generate summary
    try:
        summary_messages = [
            LLMMessage(role="system", content=COMPRESSION_PROMPT),
            LLMMessage(role="user", content=text_to_summarize),
        ]
        response = await provider.chat(
            messages=summary_messages,
            think_budget=THINK_BUDGET_SMALL,
        )
        summary_text = response.content or ""

        if not summary_text.strip():
            # Fallback: simple truncation
            logger.warning("Compression produced empty summary, falling back to truncation")
            return truncate_tool_results(messages[-keep_recent * 2:])

        # Build compressed history
        summary_msg = LLMMessage(
            role="system",
            content=f"[대화 요약] 이전 {len(old_messages)}개 메시지의 요약:\n\n{summary_text}",
        )

        logger.info(
            "Compressed %d messages into summary (%d chars), keeping %d recent",
            len(old_messages), len(summary_text), len(recent_messages),
        )

        return [summary_msg] + recent_messages

    except Exception as e:
        logger.warning("Compression failed: %s, falling back to truncation", e)
        # Fallback: just truncate tool results and keep recent
        return truncate_tool_results(messages[-keep_recent * 2:])
