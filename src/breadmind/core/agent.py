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
from breadmind.core.conversation_manager import ConversationManager
from breadmind.core.tool_coordinator import ToolCoordinator

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
        prompt_builder: object | None = None,
        orchestrator: object | None = None,
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
        self._tool_coordinator = ToolCoordinator(
            tool_registry=tool_registry,
            safety_guard=safety_guard,
            tool_timeout=tool_timeout,
            audit_logger=audit_logger,
        )
        self._pending_approvals = self._tool_coordinator.pending_approvals
        self._behavior_prompt = behavior_prompt
        self._notifications: list[str] = []
        self._behavior_tracker: object | None = None
        self._profiler = profiler
        self._prompt_builder = prompt_builder
        self._orchestrator = orchestrator
        self._provider_name: str = ""
        self._persona: str = "professional"
        self._role: str | None = None
        self._prompt_context: object | None = None
        self._conversation = ConversationManager(
            working_memory=working_memory,
            context_builder=context_builder,
            summarizer=summarizer,
        )

        # If behavior_prompt provided, rebuild system_prompt with it
        if behavior_prompt is not None:
            if self._prompt_builder and self._prompt_context:
                self._prompt_context.custom_instructions = behavior_prompt
                self._rebuild_system_prompt()
            else:
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
            self._tool_coordinator._tool_timeout = tool_timeout
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
        if self._prompt_builder:
            self._persona = persona.get("preset", "professional")
            self._rebuild_system_prompt()
        else:
            from breadmind.config import build_system_prompt
            self._system_prompt = build_system_prompt(
                persona, behavior_prompt=self._behavior_prompt,
            )

    def get_behavior_prompt(self) -> str:
        if self._prompt_builder and self._prompt_context:
            return self._prompt_context.custom_instructions or ""
        return self._behavior_prompt or ""

    def set_behavior_prompt(self, prompt: str):
        self._behavior_prompt = prompt
        if self._prompt_builder and self._prompt_context:
            self._prompt_context.custom_instructions = prompt
            self._rebuild_system_prompt()
        else:
            from breadmind.config import build_system_prompt, DEFAULT_PERSONA
            self._system_prompt = build_system_prompt(
                DEFAULT_PERSONA, behavior_prompt=prompt,
            )

    def set_custom_instructions(self, text: str | None):
        """Set custom instructions (replaces set_system_prompt for new architecture)."""
        if self._prompt_builder and self._prompt_context:
            self._prompt_context.custom_instructions = text
            self._rebuild_system_prompt()
        else:
            # Legacy fallback
            if text:
                self._system_prompt = text

    def set_persona_name(self, preset: str):
        """Set persona preset."""
        if self._prompt_builder:
            self._persona = preset
            self._rebuild_system_prompt()

    def set_role(self, role: str | None):
        """Set or clear the Swarm expert role."""
        if self._prompt_builder:
            self._role = role
            self._rebuild_system_prompt()

    def _rebuild_system_prompt(self):
        """Rebuild system prompt from PromptBuilder."""
        if self._prompt_builder and self._prompt_context:
            self._system_prompt = self._prompt_builder.build(
                provider=self._provider_name,
                persona=self._persona,
                role=self._role,
                context=self._prompt_context,
            )

    def add_notification(self, message: str):
        self._notifications.append(message)

    def set_behavior_tracker(self, tracker):
        self._behavior_tracker = tracker

    async def _notify_progress(self, status: str, detail: str = ""):
        """Publish progress update via EventBus."""
        await get_event_bus().publish_fire_and_forget(Event(
            type=EventType.PROGRESS,
            data={"status": status, "detail": detail},
            source="agent",
        ))

    def get_usage(self) -> dict[str, int]:
        return dict(self._total_usage)

    def _accumulate_usage(self, response: LLMResponse) -> None:
        if response.usage:
            self._total_usage["input_tokens"] += response.usage.input_tokens
            self._total_usage["output_tokens"] += response.usage.output_tokens

    def get_pending_approvals(self) -> list[dict]:
        """Return all pending approval requests."""
        return self._tool_coordinator.get_pending_approvals()

    async def approve_tool(self, approval_id: str) -> ToolResult:
        """Approve and execute a pending tool call."""
        return await self._tool_coordinator.approve_tool(approval_id)

    def deny_tool(self, approval_id: str) -> None:
        """Deny a pending tool call."""
        self._tool_coordinator.deny_tool(approval_id)

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
        await self._emit_session_start(user, channel, session_id)

        # Step 1: Classify intent
        intent, think_budget = self._classify_intent(message, user)

        # Step 2: Route orchestrator / credential shortcuts
        early_return = await self._try_early_routing(
            message, user, channel, session_id, intent,
        )
        if early_return is not None:
            return early_return

        # Step 3: Build conversation messages and filter tools
        messages, tools = await self._prepare_conversation(
            message, user, channel, session_id, intent,
        )

        # Step 4: LLM tool-call loop
        return await self._run_llm_loop(
            messages, tools, think_budget, user, channel, session_id,
        )

    # ------------------------------------------------------------------
    # Private: session lifecycle events
    # ------------------------------------------------------------------

    async def _emit_session_start(self, user: str, channel: str, session_id: str):
        """Log and publish session start event."""
        logger.info(json.dumps({"event": "session_start", "user": user, "channel": channel}))
        await get_event_bus().publish_fire_and_forget(Event(
            type=EventType.SESSION_START,
            data={"user": user, "channel": channel, "session_id": session_id},
            source="agent",
        ))

    async def _emit_session_end(
        self, user: str, channel: str, session_id: str, reason: str | None = None,
    ):
        """Log and publish session end event."""
        data: dict = {"user": user, "channel": channel, "session_id": session_id}
        if reason:
            data["reason"] = reason
        logger.info(json.dumps({"event": "session_end", "user": user, "channel": channel, **({"reason": reason} if reason else {})}))
        await get_event_bus().publish_fire_and_forget(Event(
            type=EventType.SESSION_END, data=data, source="agent",
        ))

    def _prepend_notifications(self, content: str) -> str:
        """Prepend any pending notifications to the response content."""
        if self._notifications:
            prefix = "\n".join(self._notifications) + "\n\n"
            self._notifications.clear()
            return prefix + content
        return content

    def _finalize_response(
        self, session_id: str, content: str, messages: list[LLMMessage],
    ) -> str:
        """Store response, schedule behavior analysis, return final content."""
        final_content = self._prepend_notifications(content)
        self._conversation.store_assistant_message(session_id, final_content)
        if self._behavior_tracker is not None:
            asyncio.create_task(
                self._safe_analyze(session_id, list(messages))
            )
        return final_content

    # ------------------------------------------------------------------
    # Private: intent classification & early routing
    # ------------------------------------------------------------------

    def _classify_intent(self, message: str, user: str):
        """Classify intent, log, emit profiler, and publish event.

        Returns (intent, think_budget).
        """
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
        if self._profiler:
            self._profiler.record_intent(user, intent.category.value)
        # Fire-and-forget event (sync helper schedules it)
        asyncio.ensure_future(get_event_bus().publish_fire_and_forget(Event(
            type=EventType.INTENT_CLASSIFIED, data=intent_data, source="agent",
        )))
        return intent, think_budget

    async def _try_early_routing(
        self, message: str, user: str, channel: str, session_id: str, intent,
    ) -> str | None:
        """Attempt early routing (orchestrator, credential).

        Returns a response string if handled, or None to continue normal flow.
        """
        # Route complex tasks to Orchestrator
        if self._orchestrator and intent.complexity == "complex":
            result = await self._try_orchestrator(message, user, channel, session_id)
            if result is not None:
                return result

        # Auto-resolve credential_ref in user message — bypass LLM
        cred_result = await self._try_credential_shortcut(message)
        if cred_result is not None:
            return cred_result

        return None

    async def _try_orchestrator(
        self, message: str, user: str, channel: str, session_id: str,
    ) -> str | None:
        """Attempt to route to orchestrator. Returns result or None on failure."""
        logger.info(json.dumps({"event": "orchestrator_route", "complexity": "complex"}))
        await self._notify_progress("orchestrator", "Complex task detected, routing to orchestrator...")
        try:
            result = await self._orchestrator.run(message, user=user, channel=channel)
            self._conversation.store_assistant_message(session_id, result)
            await self._emit_session_end(user, channel, session_id, reason="orchestrator")
            return result
        except Exception as e:
            logger.warning("Orchestrator failed, falling back to single agent: %s", e)
            return None

    async def _try_credential_shortcut(self, message: str) -> str | None:
        """Auto-resolve credential_ref in the message, bypassing LLM."""
        import re as _cred_re
        cred_match = _cred_re.search(r"credential_ref:([\w:.@\-]+)", message)
        if not (cred_match and self._tools.has_tool("router_manage")):
            return None
        cred_ref = f"credential_ref:{cred_match.group(1)}"
        host_match = _cred_re.search(r"(\d+\.\d+\.\d+\.\d+)", message)
        host = host_match.group(1) if host_match else ""
        user_match = _cred_re.search(r"(\w+)@", message)
        uname = user_match.group(1) if user_match else "root"
        if host:
            try:
                result = await self._tools.execute("router_manage", {
                    "action": "connect",
                    "host": host,
                    "router_type": "openwrt",
                    "username": uname,
                    "password": cred_ref,
                })
                return result.output
            except Exception as e:
                logger.warning("Auto credential_ref connect failed: %s", e)
        return None

    # ------------------------------------------------------------------
    # Private: conversation preparation
    # ------------------------------------------------------------------

    async def _prepare_conversation(
        self, message: str, user: str, channel: str, session_id: str, intent,
    ):
        """Build messages, enrich context, filter tools. Returns (messages, tools)."""
        messages = self._conversation.build_messages(
            session_id, message, self._system_prompt, user=user, channel=channel,
        )
        messages = await self._conversation.enrich_context(
            messages, session_id, message, self._system_prompt, intent=intent,
        )

        all_tools = self._tools.get_all_definitions()
        tools = self._filter_relevant_tools(all_tools, message, intent=intent)

        return messages, tools

    # ------------------------------------------------------------------
    # Private: LLM loop
    # ------------------------------------------------------------------

    async def _run_llm_loop(
        self,
        messages: list[LLMMessage],
        tools: list,
        think_budget: int,
        user: str,
        channel: str,
        session_id: str,
    ) -> str:
        """Execute the multi-turn LLM call loop with tool execution."""
        _recent_tool_calls: list[tuple[str, str]] = []

        for turn in range(self._max_turns):
            chat_messages = await self._conversation.maybe_summarize(
                messages, tools, provider=self._provider,
            )
            await self._notify_progress("thinking", "")

            response = await self._call_llm(chat_messages, tools, think_budget, user, channel)
            if isinstance(response, str):
                # Error string from _call_llm
                return response

            if not response.has_tool_calls:
                await self._emit_session_end(user, channel, session_id)
                return self._finalize_response(session_id, response.content or "", messages)

            # Detect tool call loops
            loop_msg = self._tool_coordinator.detect_loop(
                _recent_tool_calls, response.tool_calls,
            )
            if loop_msg:
                self._conversation.store_assistant_message(session_id, loop_msg)
                return loop_msg

            # Execute tools and check for early return (REQUEST_INPUT)
            early = await self._execute_tools_and_check(
                response, messages, user, channel, session_id,
            )
            if early is not None:
                return early

        # Max turns reached
        await self._emit_session_end(user, channel, session_id, reason="max_turns")
        final = "Maximum tool call turns reached. Please try a simpler request."
        final = self._prepend_notifications(final)
        if self._behavior_tracker is not None:
            asyncio.create_task(
                self._safe_analyze(session_id, list(messages))
            )
        return final

    async def _call_llm(
        self,
        chat_messages: list[LLMMessage],
        tools: list,
        think_budget: int,
        user: str,
        channel: str,
    ) -> LLMResponse | str:
        """Make a single LLM call. Returns LLMResponse on success, or error string."""
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
        self._log_llm_call(response, duration_ms, user, channel)
        return response

    def _log_llm_call(
        self, response: LLMResponse, duration_ms: float, user: str, channel: str,
    ):
        """Log LLM call metrics and audit."""
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

    async def _execute_tools_and_check(
        self,
        response: LLMResponse,
        messages: list[LLMMessage],
        user: str,
        channel: str,
        session_id: str,
    ) -> str | None:
        """Process tool calls, inject reminders, check for REQUEST_INPUT.

        Returns an early response string, or None to continue the loop.
        """
        assistant_msg = LLMMessage(
            role="assistant", content=response.content, tool_calls=response.tool_calls,
        )
        messages.append(assistant_msg)
        self._conversation.store_message(session_id, assistant_msg)

        exec_ctx = ToolExecutionContext(
            user=user,
            channel=channel,
            session_id=session_id,
            working_memory=self._working_memory,
            audit_logger=self._audit_logger,
            tool_gap_detector=self._tool_gap_detector,
            context_builder=self._context_builder,
            pending_approvals=self._pending_approvals,
            on_new_tool_detected=self._detect_new_tool,
            _injected_provider=self._provider,
        )
        msg_count_before = len(messages)
        await self._tool_executor.process_tool_calls(
            response.tool_calls, messages, exec_ctx,
        )

        self._inject_tool_reminder(messages, msg_count_before)

        return self._check_request_input(messages, msg_count_before, session_id)

    def _inject_tool_reminder(self, messages: list[LLMMessage], msg_count_before: int):
        """Inject Iron Laws tool reminder into the last new tool message (Claude only)."""
        if not self._prompt_builder:
            return
        reminder = self._prompt_builder.render_tool_reminder(self._provider_name)
        if not reminder:
            return
        new_msgs = messages[msg_count_before:]
        for msg in reversed(new_msgs):
            if msg.role == "tool" and isinstance(msg.content, str):
                msg.content += f"\n\n{reminder}"
                break

    def _check_request_input(
        self, messages: list[LLMMessage], msg_count_before: int, session_id: str,
    ) -> str | None:
        """Check new tool messages for [REQUEST_INPUT] and return early if found."""
        import re as _re
        new_messages = messages[msg_count_before:]
        for msg in reversed(new_messages):
            if msg.role == "tool" and msg.content and "[REQUEST_INPUT]" in msg.content:
                raw = msg.content
                raw = _re.sub(r"^\[success=(?:True|False)\]\s*", "", raw)
                match = _re.search(
                    r"\[REQUEST_INPUT\]([\s\S]*?)\[/REQUEST_INPUT\]",
                    raw,
                )
                if match:
                    idx = raw.index("[REQUEST_INPUT]")
                    pre_text = raw[:idx].strip()
                    pre_text = pre_text.replace("[NEED_CREDENTIALS]", "").strip()
                    form_block = f"[REQUEST_INPUT]{match.group(1)}[/REQUEST_INPUT]"
                    direct_response = f"{pre_text}\n\n{form_block}" if pre_text else form_block
                    self._conversation.store_assistant_message(session_id, direct_response)
                    return direct_response
                break
        return None

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
        """Filter tools to a relevant subset based on message content and intent."""
        return self._tool_coordinator.filter_relevant_tools(
            tools, message, max_tools=max_tools, intent=intent,
        )
