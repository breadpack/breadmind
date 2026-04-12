"""Jupyter notebook (.ipynb) reading and cell-level editing."""

import json

from breadmind.tools.registry import tool


def _format_cell(cell: dict, idx: int) -> str:
    """Format a single notebook cell for display."""
    cell_type = cell.get("cell_type", "unknown")
    source = "".join(cell.get("source", []))
    outputs = cell.get("outputs", [])
    result = f"\n--- Cell {idx} [{cell_type}] ---\n{source}"
    for out in outputs:
        if "text" in out:
            result += f"\n[Output] {''.join(out['text'])}"
        elif "data" in out:
            for mime, data in out["data"].items():
                if mime == "text/plain":
                    result += f"\n[Output] {''.join(data)}"
                else:
                    result += f"\n[Output: {mime}]"
    return result


@tool(
    description="Read a Jupyter notebook, returning all cells with outputs",
    read_only=True,
)
def notebook_read(file_path: str, cell_number: int = -1) -> str:
    """Read notebook. If cell_number >= 0, return only that cell."""
    with open(file_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    cells = nb.get("cells", [])
    if cell_number >= 0:
        if cell_number >= len(cells):
            return (
                f"Error: cell {cell_number} not found "
                f"(notebook has {len(cells)} cells)"
            )
        return _format_cell(cells[cell_number], cell_number)
    parts = [f"Notebook: {file_path} ({len(cells)} cells)"]
    for i, cell in enumerate(cells):
        parts.append(_format_cell(cell, i))
    return "\n".join(parts)


@tool(
    description="Edit a notebook cell by index. "
    "Actions: replace, insert_after, insert_before, delete",
    read_only=False,
)
def notebook_edit(
    file_path: str,
    cell_number: int,
    action: str = "replace",
    new_source: str = "",
    cell_type: str = "code",
) -> str:
    """Edit a notebook cell by index."""
    with open(file_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    cells = nb.get("cells", [])

    if action == "replace":
        if cell_number >= len(cells):
            return f"Error: cell {cell_number} not found"
        cells[cell_number]["source"] = new_source.splitlines(keepends=True)
        cells[cell_number]["outputs"] = []
    elif action == "insert_after":
        new_cell = {
            "cell_type": cell_type,
            "source": new_source.splitlines(keepends=True),
            "metadata": {},
            "outputs": [],
        }
        cells.insert(cell_number + 1, new_cell)
    elif action == "insert_before":
        new_cell = {
            "cell_type": cell_type,
            "source": new_source.splitlines(keepends=True),
            "metadata": {},
            "outputs": [],
        }
        cells.insert(cell_number, new_cell)
    elif action == "delete":
        if cell_number >= len(cells):
            return f"Error: cell {cell_number} not found"
        cells.pop(cell_number)
    else:
        return f"Error: unknown action '{action}'"

    nb["cells"] = cells
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
    return f"Notebook {action} on cell {cell_number} successful."
