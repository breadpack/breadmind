from __future__ import annotations
import asyncio
from breadmind.core.protocols import ToolCall, ToolDefinition, ToolFilter, ToolResult, ToolSchema, ExecutionContext


class HybridToolRegistry:
    """의도 기반 + deferred 하이브리드 도구 레지스트리."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._executors: dict[str, callable] = {}

    def register_tool_search(self) -> None:
        """ToolSearchExecutor를 자동 등록한다. tool_search는 항상 always_include에 포함."""
        from breadmind.plugins.builtin.tools.tool_search import (
            TOOL_SEARCH_DEFINITION,
            ToolSearchExecutor,
        )
        executor = ToolSearchExecutor(self)
        self.register(TOOL_SEARCH_DEFINITION, executor.execute)

    def register(self, tool: ToolDefinition, executor: callable | None = None) -> None:
        self._tools[tool.name] = tool
        if executor:
            self._executors[tool.name] = executor

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._executors.pop(name, None)

    def get_schemas(self, filter: ToolFilter | None = None) -> list[ToolSchema]:
        if filter is None:
            return [ToolSchema(name=t.name, deferred=False, definition=t) for t in self._tools.values()]
        if filter.use_deferred:
            return self._get_deferred_schemas(filter)
        if filter.intent or filter.keywords:
            return self._get_intent_filtered(filter)
        return [ToolSchema(name=t.name, deferred=False, definition=t) for t in self._tools.values()]

    def get_deferred_tools(self) -> list[str]:
        return list(self._tools.keys())

    def resolve_deferred(self, names: list[str]) -> list[ToolSchema]:
        return [ToolSchema(name=n, deferred=False, definition=self._tools[n]) for n in names if n in self._tools]

    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult:
        executor = self._executors.get(call.name)
        if not executor:
            return ToolResult(success=False, output="", error=f"No executor for tool '{call.name}'")
        try:
            output = await executor(**call.arguments)
            return ToolResult(success=True, output=str(output))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    async def execute_batch(self, calls: list[ToolCall], ctx: ExecutionContext) -> list[ToolResult]:
        """연속된 readonly 도구는 병렬, 쓰기 도구는 직렬로 실행."""
        if not calls:
            return []

        results: dict[int, ToolResult] = {}

        # 연속된 readonly 도구를 배치로 묶고, 쓰기 도구는 개별 처리
        batches: list[list[tuple[int, ToolCall]]] = []
        current_batch: list[tuple[int, ToolCall]] = []
        current_is_readonly: bool | None = None

        for i, call in enumerate(calls):
            tool_def = self._tools.get(call.name)
            is_readonly = tool_def.readonly if tool_def else False

            if is_readonly:
                if current_is_readonly is True:
                    current_batch.append((i, call))
                else:
                    if current_batch:
                        batches.append(current_batch)
                    current_batch = [(i, call)]
                    current_is_readonly = True
            else:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [(i, call)]
                current_is_readonly = False

        if current_batch:
            batches.append(current_batch)

        for batch in batches:
            if len(batch) == 1 or not self._tools.get(batch[0][1].name, ToolDefinition("", "", {})).readonly:
                # 직렬 실행 (쓰기 도구 또는 단일 도구)
                for idx, call in batch:
                    results[idx] = await self.execute(call, ctx)
            else:
                # 병렬 실행 (readonly 배치)
                coros = [self.execute(call, ctx) for _, call in batch]
                batch_results = await asyncio.gather(*coros)
                for (idx, _), result in zip(batch, batch_results):
                    results[idx] = result

        return [results[i] for i in range(len(calls))]

    def _get_deferred_schemas(self, filter: ToolFilter) -> list[ToolSchema]:
        always = set(filter.always_include)
        return [
            ToolSchema(name=n, deferred=n not in always, definition=t if n in always else None)
            for n, t in self._tools.items()
        ]

    def _get_intent_filtered(self, filter: ToolFilter) -> list[ToolSchema]:
        scored = []
        keywords = set(filter.keywords or [])
        intent = (filter.intent or "").lower()
        for name, tool in self._tools.items():
            score = 0.0
            if intent and intent in name.lower():
                score += 10.0
            for kw in keywords:
                if kw.lower() in name.lower() or kw.lower() in tool.description.lower():
                    score += 5.0
            scored.append((score, name, tool))
        scored.sort(key=lambda x: -x[0])
        max_tools = filter.max_tools or len(scored)
        return [ToolSchema(name=n, deferred=False, definition=t) for _, n, t in scored[:max_tools]]
