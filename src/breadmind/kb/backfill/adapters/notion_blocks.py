"""Block tree flattening and markdown conversion for Notion pages (§3.2).

Contains:
- Rich-text / title / parent-ref extraction helpers
- _flatten_blocks(): recursive block-tree → markdown
- _render_block(): single-block renderer
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.kb.backfill.adapters.notion_client import NotionClient

# Block tree depth cap (§3.2).
_MAX_DEPTH = 8
_DEPTH_TRUNCATION_MARKER = "... [content truncated at depth limit]"


def _extract_rich_text(rich_text_list: list[dict[str, Any]]) -> str:
    """Join plain_text from a Notion rich_text array."""
    return "".join(t.get("plain_text", "") for t in rich_text_list)


def _extract_title(page: dict[str, Any]) -> str:
    """Extract plain-text title from a page or database object."""
    props = page.get("properties", {})
    for key in ("title", "Title", "Name"):
        prop = props.get(key)
        if prop and prop.get("type") == "title":
            return _extract_rich_text(prop.get("title", []))
        if prop and prop.get("title"):
            return _extract_rich_text(prop["title"])
    # Database objects expose title at top level
    top_title = page.get("title")
    if isinstance(top_title, list):
        return _extract_rich_text(top_title)
    return "(untitled)"


def _make_parent_ref(parent: dict[str, Any]) -> str | None:
    """Build parent_ref from a Notion page/block parent descriptor (D3)."""
    ptype = parent.get("type")
    if ptype == "workspace":
        return None
    if ptype == "page_id":
        return f"notion_page:{parent['page_id']}"
    if ptype == "database_id":
        return f"notion_database:{parent['database_id']}"
    return None


# ---------------------------------------------------------------------------
# Block-tree → markdown flattener
# ---------------------------------------------------------------------------


async def _flatten_blocks(
    client: "NotionClient",
    root_block_id: str,
    depth: int = 0,
    *,
    db_queue: list[str] | None = None,
) -> str:
    """Recursively fetch block children and render to markdown.

    Args:
        client: Notion API client.
        root_block_id: Block or page ID whose children to flatten.
        depth: Current recursion depth (0 = top level).
        db_queue: Mutable list to append child_database IDs for later queuing.

    Returns:
        Markdown string representation of the block tree.
    """
    if depth >= _MAX_DEPTH:
        return _DEPTH_TRUNCATION_MARKER + "\n"

    lines: list[str] = []
    start_cursor: str | None = None

    while True:
        resp = await client.list_block_children(root_block_id, start_cursor=start_cursor)
        for block in resp.get("results", []):
            text = await _render_block(client, block, depth, db_queue=db_queue)
            if text:
                lines.append(text)
        if not resp.get("has_more"):
            break
        start_cursor = resp.get("next_cursor")

    return "\n".join(lines)


async def _render_block(
    client: "NotionClient",
    block: dict[str, Any],
    depth: int,
    *,
    db_queue: list[str] | None = None,
) -> str:
    """Render a single block to markdown text (§3.2 table)."""
    btype = block.get("type", "")
    data = block.get(btype, {})
    indent = "  " * depth

    # Rich-text types
    if btype == "paragraph":
        return indent + _extract_rich_text(data.get("rich_text", []))
    if btype == "quote":
        text = _extract_rich_text(data.get("rich_text", []))
        return indent + f"> {text}"
    if btype == "callout":
        text = _extract_rich_text(data.get("rich_text", []))
        icon = data.get("icon", {}).get("emoji", "")
        return indent + f"{icon} {text}".strip()
    if btype in ("heading_1", "heading_2", "heading_3"):
        level = int(btype[-1])
        text = _extract_rich_text(data.get("rich_text", []))
        return indent + "#" * level + " " + text
    if btype == "bulleted_list_item":
        text = _extract_rich_text(data.get("rich_text", []))
        children_text = ""
        if block.get("has_children") and depth < _MAX_DEPTH:
            children_text = "\n" + await _flatten_blocks(
                client, block["id"], depth + 1, db_queue=db_queue
            )
        return indent + f"- {text}" + children_text
    if btype == "numbered_list_item":
        text = _extract_rich_text(data.get("rich_text", []))
        children_text = ""
        if block.get("has_children") and depth < _MAX_DEPTH:
            children_text = "\n" + await _flatten_blocks(
                client, block["id"], depth + 1, db_queue=db_queue
            )
        return indent + f"1. {text}" + children_text
    if btype == "to_do":
        checked = data.get("checked", False)
        text = _extract_rich_text(data.get("rich_text", []))
        checkbox = "[x]" if checked else "[ ]"
        return indent + f"- {checkbox} {text}"
    if btype == "code":
        lang = data.get("language", "")
        text = _extract_rich_text(data.get("rich_text", []))
        return indent + f"```{lang}\n{text}\n```"
    if btype == "toggle":
        summary = _extract_rich_text(data.get("rich_text", []))
        children_text = ""
        if block.get("has_children") and depth < _MAX_DEPTH:
            children_text = "\n" + await _flatten_blocks(
                client, block["id"], depth + 1, db_queue=db_queue
            )
        return indent + summary + children_text
    if btype == "equation":
        expr = data.get("expression", "")
        return indent + f"$${expr}$$"
    if btype == "divider":
        return ""  # drop
    if btype in ("breadcrumb", "table_of_contents"):
        return ""  # drop
    if btype in ("image", "file", "pdf", "video", "audio", "bookmark"):
        # P3 placeholder
        caption = _extract_rich_text(data.get("caption", []))
        name = caption or data.get("name", btype)
        return indent + f"[file: {name}]"
    if btype == "table":
        # Table rows come as children
        if block.get("has_children") and depth < _MAX_DEPTH:
            rows_text = await _flatten_blocks(
                client, block["id"], depth, db_queue=db_queue
            )
            return rows_text
        return ""
    if btype == "table_row":
        cells = data.get("cells", [])
        cell_texts = [_extract_rich_text(cell) for cell in cells]
        return indent + "| " + " | ".join(cell_texts) + " |"
    if btype == "synced_block":
        # Render original only (spec §3.2: mirror is cross-ref only)
        synced_from = data.get("synced_from")
        if synced_from is None:
            # This IS the original
            if block.get("has_children") and depth < _MAX_DEPTH:
                return await _flatten_blocks(
                    client, block["id"], depth, db_queue=db_queue
                )
        return ""  # mirror — skip body
    if btype in ("column_list", "column"):
        # Flatten columns as simple concat (spec §3.2: column info loss OK)
        if block.get("has_children") and depth < _MAX_DEPTH:
            return await _flatten_blocks(
                client, block["id"], depth, db_queue=db_queue
            )
        return ""
    if btype == "child_page":
        # Separate discover entry — do not recurse here (spec §3.2)
        return ""
    if btype == "child_database":
        # Queue for separate DB enumeration (spec §3.2 / Task 6)
        db_id = block.get("id", "")
        if db_queue is not None and db_id:
            db_queue.append(db_id)
        return ""
    # Unknown block types — drop silently
    return ""
