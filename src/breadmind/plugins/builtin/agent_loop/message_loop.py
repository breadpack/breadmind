from __future__ import annotations
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable
from breadmind.core.logging import generate_trace_id, set_request_context
from breadmind.core.protocols import (
    AgentContext, AgentProtocol, AgentResponse, ExecutionContext,
    LLMResponse, Message, PromptContext, ProviderProtocol,
    ToolCall, ToolFilter,
)
from breadmind.core.sanitizer import InputSanitizer
from breadmind.plugins.builtin.safety.approval import ApprovalHandler, ApprovalRequest
from breadmind.plugins.builtin.safety.guard import SafetyGuard
from breadmind.plugins.builtin.safety.hooks import HookRunner
from breadmind.utils.helpers import generate_short_id

if TYPE_CHECKING:
    from breadmind.plugins.builtin.agent_loop.auto_compact import AutoCompactor
    from breadmind.plugins.builtin.agent_loop.cost_tracker import CostTracker
    from breadmind.plugins.builtin.agent_loop.spawner import Spawner
    from breadmind.plugins.builtin.memory.conversation_store import ConversationStore
    from breadmind.plugins.builtin.safety.audit import AuditLog
    from breadmind.plugins.builtin.tools.output_limiter import OutputLimiter

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """스트리밍 모드에서 yield되는 이벤트."""
    type: str  # "text", "tool_start", "tool_end", "compact", "error", "done"
    data: Any = None


@dataclass
class MessageLoopConfig:
    """Optional configuration for MessageLoopAgent."""
    max_turns: int = 10
    memory: Any | None = None
    prompt_context: PromptContext | None = None
    hook_runner: HookRunner | None = None
    auto_compactor: AutoCompactor | None = None
    output_limiter: OutputLimiter | None = None
    spawner_factory: Callable[..., Spawner] | None = None
    conversation_store: ConversationStore | None = None
    approval_handler: ApprovalHandler | None = None
    cost_tracker: CostTracker | None = None
    audit_log: AuditLog | None = None
    sanitizer: InputSanitizer | None = None


class MessageLoopAgent:
    """기본 메시지 루프 에이전트."""

    def __init__(self, provider: ProviderProtocol, prompt_builder: Any,
                 tool_registry: Any, safety_guard: SafetyGuard,
                 config: MessageLoopConfig | None = None,
                 **kwargs: Any) -> None:
        if config is None:
            config = MessageLoopConfig(**kwargs)
        elif kwargs:
            raise TypeError(
                "Cannot pass both 'config' and individual keyword arguments"
            )
        self._provider = provider
        self._prompt_builder = prompt_builder
        self._tool_registry = tool_registry
        self._safety = safety_guard
        self._config = config
        self._max_turns = config.max_turns
        self._memory = config.memory
        self._prompt_context = config.prompt_context or PromptContext()
        self._agent_id = f"agent_{generate_short_id()}"
        self._hook_runner = config.hook_runner
        self._auto_compactor = config.auto_compactor
        self._output_limiter = config.output_limiter
        self._spawner_factory = config.spawner_factory
        self._spawner: Spawner | None = None
        self._resolved_tools: set[str] = set()
        self._conversation_store = config.conversation_store
        self._approval_handler = config.approval_handler
        self._cost_tracker = config.cost_tracker
        self._audit_log = config.audit_log
        self._sanitizer = config.sanitizer

    @property
    def agent_id(self) -> str:
        return self._agent_id

    async def handle_message(self, message: str, ctx: AgentContext) -> AgentResponse:
        # Request trace context 설정
        trace_id = generate_trace_id()
        set_request_context(
            trace_id=trace_id,
            user=ctx.user,
            channel=ctx.channel,
            session_id=ctx.session_id,
        )
        logger.info("handle_message started [trace_id=%s]", trace_id)

        # Input sanitization
        if self._sanitizer:
            message = self._sanitizer.sanitize_message(message)
            detected, pattern = self._sanitizer.check_prompt_injection(message)
            if detected:
                logger.warning(
                    "Prompt injection detected [trace_id=%s, pattern=%s, user=%s]",
                    trace_id, pattern, ctx.user,
                )

        # 멀티모달: 이미지 경로 추출 및 Attachment 변환
        from breadmind.plugins.builtin.tools.multimodal import process_message_attachments
        clean_message, attachments = process_message_attachments(message)

        blocks = self._prompt_builder.build(self._prompt_context)

        # provider가 prompt_caching을 지원하면 블록 배열을 전달
        if self._provider.supports_feature("prompt_caching"):
            system_content = "\n\n".join(b.content for b in blocks if b.content)
            if hasattr(self._provider, "set_system_blocks"):
                self._provider.set_system_blocks(blocks)
        else:
            system_content = "\n\n".join(b.content for b in blocks if b.content)

        # Resume: restore previous conversation if requested
        messages: list[Message] = []
        if ctx.resume and self._conversation_store:
            restored = await self._conversation_store.load_conversation(ctx.session_id)
            if restored:
                messages = restored
                logger.info("Resumed conversation %s (%d messages)",
                            ctx.session_id, len(messages))

        if not messages:
            messages = [Message(role="system", content=system_content)]

        messages.append(Message(role="user", content=clean_message, attachments=attachments))

        use_deferred = self._provider.supports_feature("tool_search")
        if use_deferred:
            tool_filter = ToolFilter(
                use_deferred=True,
                always_include=["tool_search"],
            )
            tool_schemas = self._tool_registry.get_schemas(tool_filter)
        else:
            tool_schemas = self._tool_registry.get_schemas()

        tools = self._build_tools_list(tool_schemas)

        total_tool_calls = 0
        total_tokens = 0

        for turn in range(self._max_turns):
            logger.info("Turn %d started [trace_id=%s]", turn + 1, trace_id)

            # Auto-compact: threshold 초과 시 오래된 메시지 압축
            if self._auto_compactor and self._auto_compactor.should_compact(messages):
                logger.info("Auto-compact triggered (tokens estimate: %d)",
                            self._auto_compactor.estimate_tokens(messages))
                messages = await self._auto_compactor.compact(messages)

            _chat_start = time.perf_counter()
            try:
                response: LLMResponse = await self._provider.chat(messages, tools)
            except Exception as e:
                error_str = str(e).lower()
                if "too long" in error_str or "context" in error_str or "token" in error_str:
                    # Context overflow - emergency compact and retry
                    logger.warning("Context overflow detected, performing emergency compaction")
                    if self._auto_compactor:
                        messages = await self._auto_compactor.compact(messages, force_level=4)
                        try:
                            response = await self._provider.chat(messages, tools)
                        except Exception:
                            return AgentResponse(
                                content="Context overflow: unable to recover after emergency compaction.",
                                tool_calls_count=total_tool_calls,
                                tokens_used=total_tokens,
                                cost_usd=self._cost_tracker.total_cost if self._cost_tracker else 0.0,
                            )
                    else:
                        return AgentResponse(
                            content="Context overflow: message history too large.",
                            tool_calls_count=total_tool_calls,
                            tokens_used=total_tokens,
                            cost_usd=self._cost_tracker.total_cost if self._cost_tracker else 0.0,
                        )
                else:
                    raise
            _chat_duration = time.perf_counter() - _chat_start
            llm_elapsed_ms = _chat_duration * 1000
            total_tokens += response.usage.total_tokens
            self._record_usage(response, duration=_chat_duration)

            # Record metrics via OTel if available
            try:
                from breadmind.core.otel import get_otel
                otel = get_otel()
                if otel.available and response.usage:
                    otel.record_token_usage(
                        response.usage.input_tokens, response.usage.output_tokens,
                        model=getattr(self._provider, 'default_model', ''),
                    )
                    otel.record_llm_latency(
                        llm_elapsed_ms,
                        model=getattr(self._provider, 'default_model', ''),
                    )
            except Exception:
                pass  # OTel is best-effort

            if not response.has_tool_calls:
                # Append assistant reply and persist
                messages.append(Message(role="assistant", content=response.content))
                await self._persist_conversation(
                    ctx, messages, total_tokens,
                )
                logger.info(
                    "Turn %d ended (final) [trace_id=%s, tokens=%d]",
                    turn + 1, trace_id, total_tokens,
                )
                return AgentResponse(
                    content=response.content or "",
                    tool_calls_count=total_tool_calls,
                    tokens_used=total_tokens,
                    cost_usd=self._cost_tracker.total_cost if self._cost_tracker else 0.0,
                )

            # Tool call processing
            assistant_msg = Message(
                role="assistant", content=response.content,
                tool_calls=response.tool_calls,
            )
            messages.append(assistant_msg)

            exec_ctx = ExecutionContext(
                user=ctx.user, channel=ctx.channel,
                session_id=ctx.session_id, autonomy="auto",
            )

            # Phase 1: Safety check + pre-hook → blocked/allowed 분류
            allowed_calls: list[ToolCall] = []
            for tc in response.tool_calls:
                total_tool_calls += 1

                verdict = self._safety.check(tc.name, tc.arguments)
                if not verdict.allowed:
                    messages.append(Message(
                        role="tool", content=f"Blocked: {verdict.reason}",
                        tool_call_id=tc.id,
                    ))
                    continue

                # Approval flow: needs_approval이고 handler가 있으면 승인 요청
                if verdict.needs_approval and self._approval_handler:
                    approval_req = ApprovalRequest.create(
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        reason=verdict.reason,
                    )
                    approval_resp = await self._approval_handler.request_approval(
                        approval_req,
                    )
                    if not approval_resp.approved:
                        messages.append(Message(
                            role="tool",
                            content=f"User denied: {tc.name}",
                            tool_call_id=tc.id,
                        ))
                        continue
                    if approval_resp.modified_arguments is not None:
                        tc = type(tc)(
                            id=tc.id,
                            name=tc.name,
                            arguments=approval_resp.modified_arguments,
                        )

                if self._hook_runner:
                    hook_result = await self._hook_runner.run_pre_tool_use(
                        tc.name, tc.arguments,
                    )
                    if not hook_result.passed:
                        reason = hook_result.error or "Pre-tool hook denied"
                        logger.warning(
                            "Hook denied tool %s: %s", tc.name, reason,
                        )
                        messages.append(Message(
                            role="tool",
                            content=f"Blocked by hook: {reason}",
                            tool_call_id=tc.id,
                        ))
                        continue

                allowed_calls.append(
                    ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments),
                )

            # Phase 2: Batch 실행 (readonly 병렬, 쓰기 직렬)
            if allowed_calls:
                if hasattr(self._tool_registry, "execute_batch"):
                    results = await self._tool_registry.execute_batch(
                        allowed_calls, exec_ctx,
                    )
                else:
                    results = [
                        await self._tool_registry.execute(c, exec_ctx)
                        for c in allowed_calls
                    ]

                for call, result in zip(allowed_calls, results):
                    logger.info(
                        "Tool execution completed: %s [trace_id=%s, success=%s]",
                        call.name, trace_id, result.success,
                    )

                    # Output limiter: 도구 출력 크기 제한
                    if self._output_limiter:
                        result = self._output_limiter.limit_tool_result(result)

                    result_content = (
                        result.output if result.success
                        else f"Error: {result.error}"
                    )

                    # tool_search 결과로 새 도구가 resolve되면 tools 목록에 추가
                    if call.name == "tool_search" and result.success and use_deferred:
                        tools = self._merge_resolved_tools(tools, call.arguments)

                    # Post-tool-use hook (logging only, does not block)
                    if self._hook_runner:
                        post_result = await self._hook_runner.run_post_tool_use(
                            call.name, call.arguments, result_content,
                        )
                        if post_result.error:
                            logger.warning(
                                "Post-tool hook error for %s: %s",
                                call.name, post_result.error,
                            )

                    messages.append(Message(
                        role="tool",
                        content=result_content,
                        tool_call_id=call.id,
                    ))

            logger.info("Turn %d ended [trace_id=%s]", turn + 1, trace_id)

        logger.info("handle_message ended (max turns) [trace_id=%s]", trace_id)
        await self._persist_conversation(ctx, messages, total_tokens)
        return AgentResponse(
            content="Max turns reached.",
            tool_calls_count=total_tool_calls,
            tokens_used=total_tokens,
            cost_usd=self._cost_tracker.total_cost if self._cost_tracker else 0.0,
        )

    async def handle_message_stream(
        self, message: str, ctx: AgentContext,
    ) -> AsyncGenerator[StreamEvent, None]:
        """스트리밍 모드: 텍스트 청크와 도구 실행 상태를 실시간 yield한다.

        tool_calls가 있는 turn은 비스트리밍 chat()으로 처리하고,
        마지막 텍스트 응답만 chat_stream()으로 스트리밍한다.
        """
        # Request trace context 설정
        stream_trace_id = generate_trace_id()
        set_request_context(
            trace_id=stream_trace_id,
            user=ctx.user,
            channel=ctx.channel,
            session_id=ctx.session_id,
        )
        logger.info("handle_message_stream started [trace_id=%s]", stream_trace_id)

        # Input sanitization
        if self._sanitizer:
            message = self._sanitizer.sanitize_message(message)
            detected, pattern = self._sanitizer.check_prompt_injection(message)
            if detected:
                logger.warning(
                    "Prompt injection detected [trace_id=%s, pattern=%s, user=%s]",
                    stream_trace_id, pattern, ctx.user,
                )

        # 멀티모달: 이미지 경로 추출 및 Attachment 변환
        from breadmind.plugins.builtin.tools.multimodal import process_message_attachments
        clean_message, attachments = process_message_attachments(message)

        blocks = self._prompt_builder.build(self._prompt_context)

        if self._provider.supports_feature("prompt_caching"):
            system_content = "\n\n".join(b.content for b in blocks if b.content)
            if hasattr(self._provider, "set_system_blocks"):
                self._provider.set_system_blocks(blocks)
        else:
            system_content = "\n\n".join(b.content for b in blocks if b.content)

        messages: list[Message] = []
        if ctx.resume and self._conversation_store:
            restored = await self._conversation_store.load_conversation(ctx.session_id)
            if restored:
                messages = restored

        if not messages:
            messages = [Message(role="system", content=system_content)]

        messages.append(Message(role="user", content=clean_message, attachments=attachments))

        use_deferred = self._provider.supports_feature("tool_search")
        if use_deferred:
            tool_filter = ToolFilter(use_deferred=True, always_include=["tool_search"])
            tool_schemas = self._tool_registry.get_schemas(tool_filter)
        else:
            tool_schemas = self._tool_registry.get_schemas()

        tools = self._build_tools_list(tool_schemas)

        total_tool_calls = 0
        total_tokens = 0

        try:
            for _ in range(self._max_turns):
                # Auto-compact
                if self._auto_compactor and self._auto_compactor.should_compact(messages):
                    messages = await self._auto_compactor.compact(messages)
                    yield StreamEvent("compact", None)

                # 비스트리밍 chat()으로 먼저 호출하여 tool_calls 여부 확인
                _chat_start = time.perf_counter()
                response: LLMResponse = await self._provider.chat(messages, tools)
                _chat_duration = time.perf_counter() - _chat_start
                total_tokens += response.usage.total_tokens
                self._record_usage(response, duration=_chat_duration)

                if not response.has_tool_calls:
                    # 마지막 응답 = 텍스트 → 스트리밍으로 재호출
                    messages.append(Message(role="assistant", content=response.content))

                    if hasattr(self._provider, "chat_stream"):
                        try:
                            async for chunk in self._provider.chat_stream(messages[:-1]):
                                yield StreamEvent("text", chunk)
                        except Exception:
                            # 스트리밍 실패 시 전체 응답을 한 번에 전송
                            if response.content:
                                yield StreamEvent("text", response.content)
                    else:
                        if response.content:
                            yield StreamEvent("text", response.content)

                    await self._persist_conversation(ctx, messages, total_tokens)
                    yield StreamEvent("done", self._build_done_data(
                        total_tokens, total_tool_calls,
                    ))
                    return

                # Tool call turn: 비스트리밍 처리
                assistant_msg = Message(
                    role="assistant", content=response.content,
                    tool_calls=response.tool_calls,
                )
                messages.append(assistant_msg)

                exec_ctx = ExecutionContext(
                    user=ctx.user, channel=ctx.channel,
                    session_id=ctx.session_id, autonomy="auto",
                )

                tool_names = [tc.name for tc in response.tool_calls]
                yield StreamEvent("tool_start", {"tools": tool_names})

                # Safety check + hook
                allowed_calls: list[ToolCall] = []
                for tc in response.tool_calls:
                    total_tool_calls += 1

                    verdict = self._safety.check(tc.name, tc.arguments)
                    if not verdict.allowed:
                        messages.append(Message(
                            role="tool", content=f"Blocked: {verdict.reason}",
                            tool_call_id=tc.id,
                        ))
                        continue

                    if verdict.needs_approval and self._approval_handler:
                        approval_req = ApprovalRequest.create(
                            tool_name=tc.name, arguments=tc.arguments,
                            reason=verdict.reason,
                        )
                        approval_resp = await self._approval_handler.request_approval(
                            approval_req,
                        )
                        if not approval_resp.approved:
                            messages.append(Message(
                                role="tool", content=f"User denied: {tc.name}",
                                tool_call_id=tc.id,
                            ))
                            continue
                        if approval_resp.modified_arguments is not None:
                            tc = type(tc)(
                                id=tc.id, name=tc.name,
                                arguments=approval_resp.modified_arguments,
                            )

                    if self._hook_runner:
                        hook_result = await self._hook_runner.run_pre_tool_use(
                            tc.name, tc.arguments,
                        )
                        if not hook_result.passed:
                            reason = hook_result.error or "Pre-tool hook denied"
                            messages.append(Message(
                                role="tool", content=f"Blocked by hook: {reason}",
                                tool_call_id=tc.id,
                            ))
                            continue

                    allowed_calls.append(
                        ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments),
                    )

                # Batch 실행
                tool_results_summary: list[dict] = []
                if allowed_calls:
                    if hasattr(self._tool_registry, "execute_batch"):
                        results = await self._tool_registry.execute_batch(
                            allowed_calls, exec_ctx,
                        )
                    else:
                        results = [
                            await self._tool_registry.execute(c, exec_ctx)
                            for c in allowed_calls
                        ]

                    for call, result in zip(allowed_calls, results):
                        if self._output_limiter:
                            result = self._output_limiter.limit_tool_result(result)

                        result_content = (
                            result.output if result.success
                            else f"Error: {result.error}"
                        )

                        if call.name == "tool_search" and result.success and use_deferred:
                            tools = self._merge_resolved_tools(tools, call.arguments)

                        if self._hook_runner:
                            post_result = await self._hook_runner.run_post_tool_use(
                                call.name, call.arguments, result_content,
                            )
                            if post_result.error:
                                logger.warning(
                                    "Post-tool hook error for %s: %s",
                                    call.name, post_result.error,
                                )

                        messages.append(Message(
                            role="tool", content=result_content,
                            tool_call_id=call.id,
                        ))
                        tool_results_summary.append({
                            "name": call.name,
                            "success": result.success,
                        })

                yield StreamEvent("tool_end", {"results": tool_results_summary})

            # Max turns reached
            await self._persist_conversation(ctx, messages, total_tokens)
            yield StreamEvent("text", "Max turns reached.")
            yield StreamEvent("done", self._build_done_data(
                total_tokens, total_tool_calls,
            ))
        except Exception as e:
            logger.exception("Streaming error")
            yield StreamEvent("error", str(e))

    def _record_usage(self, response: LLMResponse, *, duration: float = 0.0) -> None:
        """CostTracker에 LLM 응답의 토큰 사용량을 기록하고 Prometheus 메트릭에 반영한다."""
        if not self._cost_tracker:
            return
        usage = response.usage
        call_cost = self._cost_tracker.record(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation=usage.cache_creation_input_tokens,
            cache_read=usage.cache_read_input_tokens,
        )

        # Prometheus metrics
        try:
            from breadmind.core.metrics import get_metrics_registry
            registry = get_metrics_registry()
            provider_name = getattr(self._provider, "name", "unknown")
            model_name = getattr(self._provider, "model", self._cost_tracker.model)

            base_labels = {"provider": provider_name, "model": model_name}

            registry.counter(
                "breadmind_llm_requests_total",
                "Total LLM API requests",
                labels={**base_labels, "status": "ok"},
            )
            registry.counter(
                "breadmind_llm_tokens_total",
                "Total LLM tokens used",
                labels={**base_labels, "type": "input"},
                value=float(usage.input_tokens),
            )
            registry.counter(
                "breadmind_llm_tokens_total",
                "Total LLM tokens used",
                labels={**base_labels, "type": "output"},
                value=float(usage.output_tokens),
            )
            registry.counter(
                "breadmind_llm_cost_usd_total",
                "Total LLM cost in USD",
                labels=base_labels,
                value=call_cost,
            )
            if duration > 0:
                registry.histogram_observe(
                    "breadmind_llm_request_duration_seconds",
                    "LLM request duration in seconds",
                    value=duration,
                    labels=base_labels,
                )
        except Exception:
            pass  # metrics should never break the agent loop

    def _build_done_data(
        self, total_tokens: int, total_tool_calls: int,
    ) -> dict:
        """StreamEvent 'done' 이벤트의 data를 구성한다."""
        data: dict = {
            "tokens": total_tokens,
            "tool_calls": total_tool_calls,
        }
        if self._cost_tracker:
            data["cost"] = f"${self._cost_tracker.total_cost:.4f}"
            data["cost_detail"] = self._cost_tracker.format_summary()
        return data

    async def _persist_conversation(
        self, ctx: AgentContext, messages: list[Message], total_tokens: int,
    ) -> None:
        """Save the full conversation to the store if available."""
        if not self._conversation_store:
            return
        try:
            from breadmind.plugins.builtin.memory.conversation_store import ConversationMeta

            # Generate title from first user message (up to 50 chars)
            title = ""
            for msg in messages:
                if msg.role == "user" and msg.content:
                    title = msg.content[:50]
                    break

            meta = ConversationMeta(
                session_id=ctx.session_id,
                user=ctx.user,
                channel=ctx.channel,
                title=title,
                message_count=len(messages),
                total_tokens=total_tokens,
            )
            await self._conversation_store.save_conversation(
                ctx.session_id, messages, meta,
            )
        except Exception:
            logger.exception("Failed to persist conversation %s", ctx.session_id)

    async def spawn(self, prompt: str, tools: list[str] | None = None,
                    isolation: str | None = None) -> AgentProtocol:
        """서브 에이전트를 spawn하여 독립 태스크 실행."""
        if not self._spawner_factory:
            raise NotImplementedError("Spawner plugin required")
        if self._spawner is None:
            self._spawner = self._spawner_factory(
                self._provider, self._prompt_builder,
                self._tool_registry, self._safety,
            )
        child_agent = await self._spawner.spawn_child(
            parent=self, prompt=prompt, tools=tools,
        )
        return child_agent

    async def send_message(self, target: str, message: str) -> str:
        """agent_id로 자식 에이전트에 메시지 전송."""
        if self._spawner is None:
            raise NotImplementedError("No spawner initialized")
        return await self._spawner.send_to(target, message)

    def set_role(self, role: str) -> None:
        self._prompt_context.role = role

    @staticmethod
    def _build_tools_list(schemas: list) -> list[dict] | None:
        """ToolSchema 목록을 LLM provider에 전달할 dict 목록으로 변환."""
        tools = []
        for s in schemas:
            if s.definition:
                tools.append({
                    "name": s.name,
                    "description": s.definition.description,
                    "input_schema": s.definition.parameters,
                })
            elif s.deferred:
                # deferred 도구는 이름만 노출 (provider가 system prompt로 안내)
                pass
        return tools or None

    def _merge_resolved_tools(
        self, tools: list[dict] | None, query_args: dict,
    ) -> list[dict] | None:
        """tool_search 호출 후 resolve된 도구를 tools 목록에 병합."""
        query = query_args.get("query", "")
        if query.startswith("select:"):
            names = [n.strip() for n in query[7:].split(",") if n.strip()]
        else:
            # keyword 검색의 경우 resolve_deferred로 매칭된 도구를 가져옴
            max_results = query_args.get("max_results", 5)
            from breadmind.plugins.builtin.tools.tool_search import ToolSearchExecutor
            executor = ToolSearchExecutor(self._tool_registry)
            matched = executor._search_by_keywords(query, max_results)
            names = [s.name for s in matched]

        new_names = [n for n in names if n not in self._resolved_tools]
        if not new_names:
            return tools

        resolved = self._tool_registry.resolve_deferred(new_names)
        self._resolved_tools.update(n for n in new_names)

        if tools is None:
            tools = []

        existing_names = {t["name"] for t in tools}
        for schema in resolved:
            if schema.definition and schema.name not in existing_names:
                tools.append({
                    "name": schema.name,
                    "description": schema.definition.description,
                    "input_schema": schema.definition.parameters,
                })

        return tools or None
