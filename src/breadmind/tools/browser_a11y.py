"""Accessibility tree extraction via CDP with LLM-friendly compact text format."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INTERACTIVE_ROLES: frozenset[str] = frozenset({
    "button", "textbox", "checkbox", "radio", "combobox", "listbox",
    "menuitem", "link", "searchbox", "slider", "spinbutton", "switch",
    "tab", "menubar", "menu", "option", "treeitem",
})

_SKIP_ROLES: frozenset[str] = frozenset({"none", "generic", "InlineTextBox"})


@dataclass
class AXNode:
    role: str
    name: str = ""
    value: str = ""
    properties: dict[str, str] = field(default_factory=dict)
    children: list["AXNode"] = field(default_factory=list)


class A11yExtractor:
    """Extracts and formats the accessibility tree from a CDP session."""

    def __init__(self, cdp_session: Any, max_depth: int = 10) -> None:
        self._cdp = cdp_session
        self.max_depth = max_depth

    async def extract(self) -> list[AXNode]:
        """Call CDP Accessibility.getFullAXTree and parse the result."""
        result = await self._cdp.send("Accessibility.getFullAXTree", {})
        raw_nodes: list[dict] = result.get("nodes", [])
        if not raw_nodes:
            return []
        root = raw_nodes[0]
        return self._parse_children(root.get("children", []), depth=0)

    def _parse_children(self, children: list[dict], depth: int) -> list[AXNode]:
        """Recursively parse CDP raw nodes into AXNode objects."""
        if depth >= self.max_depth:
            return []

        result: list[AXNode] = []
        for raw in children:
            role = raw.get("role", {}).get("value", "")
            raw_children = raw.get("children", [])

            if role in _SKIP_ROLES:
                # Pass through to their children without creating a node
                result.extend(self._parse_children(raw_children, depth))
                continue

            name = raw.get("name", {}).get("value", "")
            value_obj = raw.get("value", {})
            value = value_obj.get("value", "") if isinstance(value_obj, dict) else ""
            properties: dict[str, str] = {
                p["name"]: p["value"]["value"]
                for p in raw.get("properties", [])
                if isinstance(p.get("value"), dict)
            }
            node_children = self._parse_children(raw_children, depth + 1)
            result.append(AXNode(
                role=role,
                name=name,
                value=value,
                properties=properties,
                children=node_children,
            ))

        return result

    @staticmethod
    def format_compact(nodes: list[AXNode], indent: int = 0) -> str:
        """Format nodes as a compact, LLM-friendly multiline string."""
        lines: list[str] = []
        prefix = " " * indent

        for node in nodes:
            parts: list[str] = [node.role]

            for k, v in node.properties.items():
                parts.append(f"{k}={v}")

            if node.name:
                parts.append(f'"{node.name}"')

            if node.value:
                parts.append(f'value="{node.value}"')

            line = prefix + "[" + " ".join(parts) + "]"
            lines.append(line)

            if node.children:
                child_text = A11yExtractor.format_compact(node.children, indent + 2)
                lines.append(child_text)

        return "\n".join(lines)

    @staticmethod
    def filter_interactive(nodes: list[AXNode]) -> list[AXNode]:
        """Return only nodes with an interactive role, recursing into all children."""
        result: list[AXNode] = []
        for node in nodes:
            if node.role in INTERACTIVE_ROLES:
                result.append(node)
            if node.children:
                result.extend(A11yExtractor.filter_interactive(node.children))
        return result

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count as roughly 1 token per 4 characters."""
        return max(1, len(text) // 4)
