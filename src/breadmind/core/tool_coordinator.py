"""Coordinates tool filtering, execution approval, and loop detection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.tools.registry import ToolRegistry, ToolResult
    from breadmind.core.audit import AuditLogger
    from breadmind.core.safety import SafetyGuard

logger = logging.getLogger("breadmind.agent")


class ToolCoordinator:
    """Handles tool selection, approval management, and loop detection."""

    # Tools that are always included regardless of relevance scoring
    ALWAYS_INCLUDE = {
        "shell_exec", "web_search", "file_read", "file_write",
        "browser", "mcp_search", "mcp_install", "mcp_list",
        "skill_manage", "memory_save", "memory_search",
        "swarm_role", "messenger_connect", "network_scan", "router_manage",
        "task_create", "task_list", "event_create", "event_list",
        "reminder_set",
    }

    LOOP_THRESHOLD = 3  # same call repeated N times = loop

    def __init__(
        self,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        tool_timeout: int = 30,
        audit_logger: AuditLogger | None = None,
    ):
        self._registry = tool_registry
        self._guard = safety_guard
        self._tool_timeout = tool_timeout
        self._audit_logger = audit_logger
        self._pending_approvals: dict[str, dict] = {}

    @property
    def pending_approvals(self) -> dict[str, dict]:
        """Expose pending_approvals dict for ToolExecutor integration."""
        return self._pending_approvals

    def get_pending_approvals(self) -> list[dict]:
        """Return all pending approval requests."""
        return [
            {"approval_id": aid, **info}
            for aid, info in self._pending_approvals.items()
            if info.get("status") == "pending"
        ]

    async def approve_tool(self, approval_id: str) -> ToolResult:
        """Approve and execute a pending tool call."""
        from breadmind.tools.registry import ToolResult

        approval = self._pending_approvals.get(approval_id)
        if approval is None or approval.get("status") != "pending":
            return ToolResult(success=False, output=f"No pending approval found: {approval_id}")

        approval["status"] = "approved"
        tool_name = approval["tool"]
        arguments = approval["args"]
        user = approval["user"]
        channel = approval["channel"]

        if self._audit_logger:
            self._audit_logger.log_approval_request(user, channel, tool_name, "approved")

        t0 = time.monotonic()
        try:
            # Check if this is a long-running task (no timeout)
            is_long = (
                tool_name == "code_delegate"
                and arguments.get("long_running", False)
            )
            if isinstance(is_long, str):
                is_long = is_long.lower() in ("true", "1", "yes")

            if is_long:
                logger.info("Executing approved %s with NO timeout (long_running)", tool_name)
                result = await self._registry.execute(tool_name, arguments)
            else:
                timeout = self._tool_timeout
                if tool_name == "code_delegate":
                    timeout = max(timeout, 600)
                result = await asyncio.wait_for(
                    self._registry.execute(tool_name, arguments),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            result = ToolResult(success=False, output=f"Tool execution timed out after {self._tool_timeout}s.")
        except Exception as e:
            logger.exception(f"Tool execution error during approval: {tool_name}")
            result = ToolResult(success=False, output=f"Tool execution error: {e}")

        duration_ms = (time.monotonic() - t0) * 1000
        if self._audit_logger:
            self._audit_logger.log_tool_call(
                user, channel, tool_name, arguments,
                result.output, result.success, duration_ms,
            )

        return result

    def deny_tool(self, approval_id: str) -> None:
        """Deny a pending tool call."""
        approval = self._pending_approvals.get(approval_id)
        if approval is not None:
            user = approval.get("user", "")
            channel = approval.get("channel", "")
            tool_name = approval.get("tool", "")
            approval["status"] = "denied"
            if self._audit_logger:
                self._audit_logger.log_approval_request(user, channel, tool_name, "denied")

    def filter_relevant_tools(
        self, tools: list, message: str, max_tools: int = 30, intent: Any = None,
    ) -> list:
        """Filter tools to a relevant subset based on message content and intent.

        Uses intent category to prioritize tools that match the user's goal,
        then falls back to keyword overlap scoring for remaining slots.
        """
        if len(tools) <= max_tools:
            return tools

        # Add intent-hinted tools to essential set
        intent_hints = set()
        if intent is not None:
            intent_hints = intent.tool_hints

        essential = []
        candidates = []
        msg_lower = message.lower()

        for t in tools:
            if t.name in self.ALWAYS_INCLUDE or t.name in intent_hints:
                essential.append(t)
            else:
                # Score by name/description overlap + intent bonus
                score = 0
                name_words = set(t.name.lower().replace("_", " ").split())
                desc_words = set((t.description or "").lower().split())
                msg_words = set(msg_lower.split())
                score = len(msg_words & name_words) * 3 + len(msg_words & desc_words)

                # Boost tools whose description matches intent keywords
                if intent is not None:
                    intent_kw_set = set(intent.keywords)
                    score += len(intent_kw_set & name_words) * 2
                    score += len(intent_kw_set & desc_words)

                candidates.append((score, t))

        candidates.sort(key=lambda x: x[0], reverse=True)
        remaining_slots = max(0, max_tools - len(essential))
        selected = essential + [t for _, t in candidates[:remaining_slots]]
        return selected

    def detect_loop(
        self,
        recent_calls: list[tuple[str, str]],
        tool_calls: list[Any],
        threshold: int | None = None,
    ) -> str | None:
        """Detect tool call loops. Returns loop message if detected, None otherwise.

        Updates recent_calls in-place by appending new entries from tool_calls.
        """
        if threshold is None:
            threshold = self.LOOP_THRESHOLD

        for tc in tool_calls:
            args_hash = hashlib.md5(
                json.dumps(tc.arguments, sort_keys=True, default=str).encode()
            ).hexdigest()[:8]
            recent_calls.append((tc.name, args_hash))

        # Check if the last N calls are identical
        if len(recent_calls) >= threshold:
            last_n = recent_calls[-threshold:]
            if len(set(last_n)) == 1:
                loop_tool = last_n[0][0]
                logger.warning(
                    "Tool call loop detected: %s called %d times with same args",
                    loop_tool, threshold,
                )
                return (
                    f"동일한 도구({loop_tool})가 같은 인자로 {threshold}회 반복 "
                    f"호출되어 중단합니다. 다른 방법을 시도해주세요."
                )

        return None
