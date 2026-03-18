from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMProvider, LLMMessage, LLMResponse
from breadmind.tools.registry import ToolRegistry, ToolResult
from breadmind.core.safety import SafetyGuard
from breadmind.core.audit import AuditLogger
from breadmind.core.tool_executor import ToolExecutor, ToolExecutionContext
from breadmind.core.events import get_event_bus, Event, EventType

if TYPE_CHECKING:
    from breadmind.memory.working import WorkingMemory
    from breadmind.core.tool_gap import ToolGapDetector

logger = logging.getLogger("breadmind.agent")


class CoreAgent:
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        system_prompt: str = "You are BreadMind, an AI infrastructure agent.",
        max_turns: int = 10,
        working_memory: WorkingMemory | None = None,
        tool_timeout: int = 30,
        chat_timeout: int = 120,
        audit_logger: AuditLogger | None = None,
        summarizer: object | None = None,
        tool_gap_detector: ToolGapDetector | None = None,
        context_builder: object | None = None,
        behavior_prompt: str | None = None,
        profiler: object | None = None,
    ):
        self._provider = provider
        self._tools = tool_registry
        self._guard = safety_guard
        self._tool_executor = ToolExecutor(tool_registry, safety_guard, tool_timeout)
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._working_memory = working_memory
        self._tool_timeout = tool_timeout
        self._chat_timeout = chat_timeout
        self._total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        self._audit_logger = audit_logger
        self._summarizer = summarizer
        self._tool_gap_detector = tool_gap_detector
        self._context_builder = context_builder
        self._pending_approvals: dict[str, dict] = {}
        self._behavior_prompt = behavior_prompt
        self._notifications: list[str] = []
        self._behavior_tracker: object | None = None
        self._progress_callback: object | None = None
        self._profiler = profiler

        # If behavior_prompt provided, rebuild system_prompt with it
        if behavior_prompt is not None:
            from breadmind.config import build_system_prompt, DEFAULT_PERSONA
            self._system_prompt = build_system_prompt(
                DEFAULT_PERSONA, behavior_prompt=behavior_prompt,
            )

    async def update_provider(self, provider: LLMProvider):
        """Replace the LLM provider at runtime, closing the old one."""
        old = self._provider
        self._provider = provider
        if old is not None:
            try:
                await old.close()
            except Exception:
                pass

    def update_timeouts(self, tool_timeout: int = None, chat_timeout: int = None):
        """Update timeout settings at runtime."""
        if tool_timeout is not None and tool_timeout >= 1:
            self._tool_timeout = tool_timeout
            self._tool_executor.tool_timeout = tool_timeout
        if chat_timeout is not None and chat_timeout >= 1:
            self._chat_timeout = chat_timeout

    def get_timeouts(self) -> dict:
        return {
            "tool_timeout": self._tool_timeout,
            "chat_timeout": self._chat_timeout,
            "max_turns": self._max_turns,
        }

    def update_max_turns(self, max_turns: int):
        if max_turns >= 1:
            self._max_turns = max_turns

    def set_system_prompt(self, prompt: str):
        self._system_prompt = prompt

    def set_persona(self, persona: dict):
        from breadmind.config import build_system_prompt
        self._system_prompt = build_system_prompt(
            persona, behavior_prompt=self._behavior_prompt,
        )

    def get_behavior_prompt(self) -> str:
        from breadmind.config import _PROACTIVE_BEHAVIOR_PROMPT
        return self._behavior_prompt or _PROACTIVE_BEHAVIOR_PROMPT

    def set_behavior_prompt(self, prompt: str):
        from breadmind.config import build_system_prompt, DEFAULT_PERSONA
        self._behavior_prompt = prompt
        self._system_prompt = build_system_prompt(
            DEFAULT_PERSONA, behavior_prompt=prompt,
        )

    def add_notification(self, message: str):
        self._notifications.append(message)

    def set_behavior_tracker(self, tracker):
        self._behavior_tracker = tracker

    def set_progress_callback(self, callback):
        """Set async callback for progress updates: callback(status, detail)."""
        self._progress_callback = callback

    async def _notify_progress(self, status: str, detail: str = ""):
        if self._progress_callback:
            try:
                await self._progress_callback(status, detail)
            except Exception:
                pass

    def get_usage(self) -> dict[str, int]:
        return dict(self._total_usage)

    def _accumulate_usage(self, response: LLMResponse) -> None:
        if response.usage:
            self._total_usage["input_tokens"] += response.usage.input_tokens
            self._total_usage["output_tokens"] += response.usage.output_tokens

    def get_pending_approvals(self) -> list[dict]:
        """Return all pending approval requests."""
        return [
            {"approval_id": aid, **info}
            for aid, info in self._pending_approvals.items()
            if info.get("status") == "pending"
        ]

    async def approve_tool(self, approval_id: str) -> ToolResult:
        """Approve and execute a pending tool call."""
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
            result = await asyncio.wait_for(
                self._tools.execute(tool_name, arguments),
                timeout=self._tool_timeout,
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

    async def resume_after_approval(
        self, approval_id: str, result: ToolResult,
    ) -> str | None:
        """Resume LLM conversation after a tool approval, injecting the result."""
        approval = self._pending_approvals.get(approval_id)
        if approval is None:
            return None

        user = approval.get("user", "")
        channel = approval.get("channel", "")
        tool_name = approval.get("tool", "")

        # Build the result summary and let handle_message process it
        status = "[success=True]" if result.success else "[success=False]"
        result_content = f"{status} {result.output}" if result.output else status

        resume_text = (
            f"[System] Tool '{tool_name}' was approved and executed.\n"
            f"Result: {result_content}\n"
            f"Summarize the result for the user."
        )

        try:
            return await self.handle_message(resume_text, user=user, channel=channel)
        except Exception:
            logger.exception("Failed to resume after approval")
            return f"Tool '{tool_name}' executed: {result_content}"

    async def handle_message(self, message: str, user: str, channel: str) -> str:
        session_id = f"{user}:{channel}"
        logger.info(json.dumps({"event": "session_start", "user": user, "channel": channel}))

        # Publish session start via EventBus (fire-and-forget)
        await get_event_bus().publish_fire_and_forget(Event(
            type=EventType.SESSION_START,
            data={"user": user, "channel": channel, "session_id": session_id},
            source="agent",
        ))

        # Step 1: Classify intent (rule-based, no LLM call)
        from breadmind.core.intent import classify as classify_intent, get_think_budget
        intent = classify_intent(message)
        think_budget = get_think_budget(intent)
        intent_data = {
            "category": intent.category.value,
            "confidence": round(intent.confidence, 2),
            "entities": intent.entities[:5],
            "think_budget": think_budget,
        }
        logger.info(json.dumps({"event": "intent_classified", **intent_data}))

        await get_event_bus().publish_fire_and_forget(Event(
            type=EventType.INTENT_CLASSIFIED,
            data=intent_data,
            source="agent",
        ))

        # Record intent for adaptive user profiling
        if self._profiler:
            self._profiler.record_intent(user, intent.category.value)

        # Build initial messages
        system_msg = LLMMessage(role="system", content=self._system_prompt)
        user_msg = LLMMessage(role="user", content=message)

        if self._working_memory is not None:
            session = self._working_memory.get_or_create_session(
                session_id, user=user, channel=channel,
            )
            previous_messages = list(session.messages)
            logger.info(json.dumps({"event": "context_build", "session": session_id, "previous_msgs": len(previous_messages)}))
            messages = [system_msg] + previous_messages + [user_msg]
            # Save a sanitized version of the user message to memory
            from breadmind.storage.credential_vault import CredentialVault
            clean_content = CredentialVault.sanitize_text(message)
            stored_user_msg = LLMMessage(role="user", content=clean_content)
            self._working_memory.add_message(session_id, stored_user_msg)
        else:
            messages = [system_msg, user_msg]

        # Step 2: Enrich context with intent-aware memory retrieval
        if self._context_builder:
            try:
                enrichment = await asyncio.wait_for(
                    self._context_builder.build_context(session_id, message, intent=intent),
                    timeout=10,
                )
                # Extract only the enrichment system messages (not conversation history)
                context_msgs = [m for m in enrichment if m.role == "system" and m.content and m.content != self._system_prompt]
                if context_msgs:
                    # Insert context after system prompt, before conversation history
                    messages = [messages[0]] + context_msgs + messages[1:]
            except Exception as e:
                logger.warning(f"ContextBuilder enrichment failed: {e}")

        # Step 3: Filter tools using intent-aware selection
        all_tools = self._tools.get_all_definitions()
        tools = self._filter_relevant_tools(all_tools, message, intent=intent)

        for turn in range(self._max_turns):
            # Apply conversation summarization if available
            chat_messages = messages
            if self._summarizer is not None and hasattr(self._summarizer, "summarize_if_needed"):
                try:
                    chat_messages = await self._summarizer.summarize_if_needed(
                        messages, tools,
                    )
                except Exception:
                    logger.exception("Summarizer error, using original messages")
                    chat_messages = messages
            else:
                # Fallback: trim messages if exceeding context window
                try:
                    from breadmind.llm.token_counter import TokenCounter
                    model = getattr(self._provider, "model_name", "claude-sonnet-4-6")
                    if not TokenCounter.fits_in_context(chat_messages, tools, model):
                        chat_messages = TokenCounter.trim_messages_to_fit(
                            chat_messages, tools, model,
                        )
                        logger.warning("Trimmed messages to fit context window")
                except Exception:
                    logger.debug("TokenCounter check skipped due to error")

            await self._notify_progress("thinking", "")

            t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    self._provider.chat(
                        messages=chat_messages,
                        tools=tools or None,
                        think_budget=think_budget,
                    ),
                    timeout=self._chat_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(json.dumps({"event": "llm_call", "status": "timeout", "user": user}))
                return "요청 시간이 초과되었습니다."
            except Exception:
                logger.exception("LLM provider error")
                return "서비스 오류가 발생했습니다."

            duration_ms = (time.monotonic() - t0) * 1000
            self._accumulate_usage(response)

            # Log LLM call
            model_name = getattr(self._provider, "model", "unknown")
            if not isinstance(model_name, str):
                model_name = "unknown"
            logger.info(json.dumps({
                "event": "llm_call",
                "model": model_name,
                "tokens": {
                    "input": response.usage.input_tokens if response.usage else 0,
                    "output": response.usage.output_tokens if response.usage else 0,
                },
                "duration_ms": round(duration_ms, 2),
            }))
            if self._audit_logger and response.usage:
                self._audit_logger.log_llm_call(
                    user, channel,
                    model=model_name,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cache_hit=getattr(response.usage, "cache_read_input_tokens", 0) > 0,
                    duration_ms=duration_ms,
                )

            if not response.has_tool_calls:
                final_content = response.content or ""
                # Prepend pending notifications
                if self._notifications:
                    prefix = "\n".join(self._notifications) + "\n\n"
                    self._notifications.clear()
                    final_content = prefix + final_content
                if self._working_memory is not None:
                    self._working_memory.add_message(
                        session_id,
                        LLMMessage(role="assistant", content=final_content),
                    )
                logger.info(json.dumps({"event": "session_end", "user": user, "channel": channel}))
                await get_event_bus().publish_fire_and_forget(Event(
                    type=EventType.SESSION_END,
                    data={"user": user, "channel": channel, "session_id": session_id},
                    source="agent",
                ))
                # Fire-and-forget behavior analysis
                if self._behavior_tracker is not None:
                    asyncio.create_task(
                        self._safe_analyze(session_id, list(messages))
                    )
                return final_content

            # Process tool calls — add assistant message, then delegate to ToolExecutor
            assistant_msg = LLMMessage(
                role="assistant", content=response.content, tool_calls=response.tool_calls,
            )
            messages.append(assistant_msg)
            if self._working_memory is not None:
                self._working_memory.add_message(session_id, assistant_msg)

            exec_ctx = ToolExecutionContext(
                user=user,
                channel=channel,
                session_id=session_id,
                working_memory=self._working_memory,
                audit_logger=self._audit_logger,
                tool_gap_detector=self._tool_gap_detector,
                context_builder=self._context_builder,
                pending_approvals=self._pending_approvals,
                notify_progress=self._notify_progress,
                on_new_tool_detected=self._detect_new_tool,
                _injected_provider=self._provider,
            )
            await self._tool_executor.process_tool_calls(
                response.tool_calls, messages, exec_ctx,
            )

            # Check if any tool returned a [REQUEST_INPUT] form — bypass LLM
            # and return directly to user so the form JSON is not corrupted
            for msg in reversed(messages):
                if msg.role == "tool" and msg.content and "[REQUEST_INPUT]" in msg.content:
                    import re as _re
                    raw = msg.content
                    # Strip [success=True/False] prefix added by ToolExecutor
                    raw = _re.sub(r"^\[success=(?:True|False)\]\s*", "", raw)
                    match = _re.search(
                        r"\[REQUEST_INPUT\]([\s\S]*?)\[/REQUEST_INPUT\]",
                        raw,
                    )
                    if match:
                        # Extract context text before the form tag
                        idx = raw.index("[REQUEST_INPUT]")
                        pre_text = raw[:idx].strip()
                        # Remove internal markers from user-facing text
                        pre_text = pre_text.replace("[NEED_CREDENTIALS]", "").strip()
                        form_block = f"[REQUEST_INPUT]{match.group(1)}[/REQUEST_INPUT]"
                        direct_response = f"{pre_text}\n\n{form_block}" if pre_text else form_block
                        if self._working_memory is not None:
                            self._working_memory.add_message(
                                session_id,
                                LLMMessage(role="assistant", content=direct_response),
                            )
                        return direct_response
                    break

        logger.info(json.dumps({"event": "session_end", "user": user, "channel": channel, "reason": "max_turns"}))
        await get_event_bus().publish_fire_and_forget(Event(
            type=EventType.SESSION_END,
            data={"user": user, "channel": channel, "session_id": session_id, "reason": "max_turns"},
            source="agent",
        ))
        final = "Maximum tool call turns reached. Please try a simpler request."
        if self._notifications:
            prefix = "\n".join(self._notifications) + "\n\n"
            self._notifications.clear()
            final = prefix + final
        if self._behavior_tracker is not None:
            asyncio.create_task(
                self._safe_analyze(session_id, list(messages))
            )
        return final

    async def _detect_new_tool(self, command: str, output: str):
        """Fire-and-forget: check if shell_exec installed or removed a tool."""
        try:
            from breadmind.core.env_scanner import detect_new_tool, detect_removed_tool
            sm = getattr(self._context_builder, '_semantic', None)
            if sm:
                tool_name = await detect_new_tool(command, output, sm)
                if tool_name:
                    self.add_notification(
                        f"[System] 새 도구 발견: {tool_name} — 환경 정보가 갱신되었습니다."
                    )
                    return
                removed = await detect_removed_tool(command, output, sm)
                if removed:
                    self.add_notification(
                        f"[System] 도구 제거 감지: {removed} — 환경 정보가 갱신되었습니다."
                    )
        except Exception:
            logger.debug("Tool detection failed", exc_info=True)

    async def _safe_analyze(self, session_id: str, messages: list[LLMMessage]):
        """Fire-and-forget behavior analysis with error protection."""
        try:
            await self._behavior_tracker.analyze(session_id, messages)
        except Exception:
            logger.exception("Behavior analysis failed")

    def _filter_relevant_tools(
        self, tools: list, message: str, max_tools: int = 30, intent=None,
    ) -> list:
        """Filter tools to a relevant subset based on message content and intent.

        Uses intent category to prioritize tools that match the user's goal,
        then falls back to keyword overlap scoring for remaining slots.
        """
        ALWAYS_INCLUDE = {
            "shell_exec", "web_search", "file_read", "file_write",
            "browser", "mcp_search", "mcp_install", "mcp_list",
            "skill_manage", "memory_save", "memory_search",
            "swarm_role", "messenger_connect", "network_scan", "router_manage",
            "task_create", "task_list", "event_create", "event_list",
            "reminder_set", "delegate_tasks",
        }

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
            if t.name in ALWAYS_INCLUDE or t.name in intent_hints:
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
