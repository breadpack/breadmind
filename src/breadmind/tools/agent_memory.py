"""MemGPT-style memory tools — let the agent manage its own memory."""
from __future__ import annotations

from breadmind.tools.registry import tool


def create_agent_memory_tools(episodic_memory, semantic_memory):
    """Create memory tools that the agent can call to manage its own memory."""

    @tool(
        description=(
            "Save important information to long-term memory. "
            "Use this to remember facts, lessons, user preferences, "
            "infrastructure details, or anything worth recalling later. "
            "Provide descriptive keywords for future retrieval."
        )
    )
    async def memory_save(
        content: str,
        keywords: str = "",
        category: str = "general",
    ) -> str:
        tags = ["agent_memory", category]
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
        note = await episodic_memory.add_note(
            content=content,
            keywords=kw_list,
            tags=tags,
            context_description=f"Agent memory: {category}",
        )
        return f"Saved to memory (id={note.id}): {content[:100]}"

    @tool(
        description=(
            "Search long-term memory for relevant information. "
            "Use keywords to find past lessons, decisions, infrastructure facts, "
            "or anything previously saved with memory_save."
        )
    )
    async def memory_search(
        keywords: str,
        limit: int = 5,
    ) -> str:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        if not kw_list:
            return "No keywords provided."
        notes = await episodic_memory.search_by_keywords(kw_list, limit=limit)
        if not notes:
            return "No matching memories found."
        lines = []
        for n in notes:
            lines.append(f"[id={n.id}] {n.content}")
        return "\n".join(lines)

    @tool(
        description=(
            "List known infrastructure entities from the knowledge graph. "
            "Search by name or type (ip_address, hostname, infrastructure, role, skill)."
        )
    )
    async def memory_entities(
        search: str = "",
        entity_type: str = "",
        limit: int = 10,
    ) -> str:
        entities = await semantic_memory.find_entities(
            entity_type=entity_type or None,
            name_contains=search or None,
        )
        if not entities:
            return "No entities found."
        lines = []
        for e in entities[:limit]:
            lines.append(f"[{e.entity_type}] {e.name}: {e.properties}")
        return "\n".join(lines)

    return {
        "memory_save": memory_save,
        "memory_search": memory_search,
        "memory_entities": memory_entities,
    }
