"""ToolSearch: LLM이 deferred tool의 full schema를 검색/로드하는 도구."""
from __future__ import annotations

from typing import TYPE_CHECKING

from breadmind.core.protocols import ToolDefinition, ToolSchema

if TYPE_CHECKING:
    from breadmind.plugins.builtin.tools.registry import HybridToolRegistry

TOOL_SEARCH_DEFINITION = ToolDefinition(
    name="tool_search",
    description=(
        "Search for available tools by keyword or exact name. "
        "Use 'select:name1,name2' for exact lookup, or keywords for fuzzy search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query: 'select:Read,Edit' for exact match, or keywords for search",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    readonly=True,
)


class ToolSearchExecutor:
    """deferred 도구를 검색하고 full schema를 반환하는 실행기."""

    def __init__(self, registry: HybridToolRegistry) -> None:
        self._registry = registry

    async def execute(self, query: str, max_results: int = 5) -> str:
        if query.startswith("select:"):
            names = [n.strip() for n in query[7:].split(",") if n.strip()]
            schemas = self._registry.resolve_deferred(names)
        else:
            schemas = self._search_by_keywords(query, max_results)

        return self._format_results(schemas)

    def _search_by_keywords(self, query: str, max_results: int) -> list[ToolSchema]:
        """도구 이름과 description에서 키워드를 검색하여 점수 기반 매칭."""
        terms = query.lower().split()
        if not terms:
            return []

        scored: list[tuple[float, ToolSchema]] = []
        for name, tool in self._registry._tools.items():
            if name == "tool_search":
                continue
            score = 0.0
            name_lower = name.lower()
            desc_lower = tool.description.lower()

            for term in terms:
                # 이름에 term이 포함되면 +가 있는 경우 필수 매칭
                if term.startswith("+"):
                    required = term[1:]
                    if required in name_lower:
                        score += 15.0
                    elif required in desc_lower:
                        score += 5.0
                    else:
                        score = -1.0
                        break
                else:
                    if term in name_lower:
                        score += 10.0
                    if term in desc_lower:
                        score += 5.0

            if score > 0:
                schema = ToolSchema(name=name, deferred=False, definition=tool)
                scored.append((score, schema))

        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:max_results]]

    def _format_results(self, schemas: list[ToolSchema]) -> str:
        """결과를 LLM이 읽기 쉬운 human-readable 텍스트로 포맷."""
        if not schemas:
            return "No matching tools found."

        lines: list[str] = [f"Found {len(schemas)} tool(s):\n"]
        for schema in schemas:
            defn = schema.definition
            if defn is None:
                lines.append(f"- {schema.name} (deferred, no schema available)")
                continue

            lines.append(f"- {defn.name}")
            lines.append(f"  Description: {defn.description}")
            if defn.readonly:
                lines.append("  Mode: readonly")

            params = defn.parameters
            props = params.get("properties", {})
            required = set(params.get("required", []))
            if props:
                lines.append("  Parameters:")
                for pname, pinfo in props.items():
                    req_mark = " (required)" if pname in required else ""
                    ptype = pinfo.get("type", "any")
                    pdesc = pinfo.get("description", "")
                    default = pinfo.get("default")
                    default_str = f", default: {default}" if default is not None else ""
                    lines.append(f"    - {pname}: {ptype}{req_mark} — {pdesc}{default_str}")
            lines.append("")

        return "\n".join(lines)
