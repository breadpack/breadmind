"""File edit tool with uniqueness-enforced string replacement."""

import os

from breadmind.tools.registry import tool

# Track which files have been read in the session
_read_files: set[str] = set()


def mark_file_read(path: str) -> None:
    """Mark a file as having been read, enabling edit operations on it."""
    _read_files.add(os.path.abspath(path))


def reset_read_tracking() -> None:
    """Clear the set of tracked read files."""
    _read_files.clear()


@tool(
    description="Read a file and track it for edit validation",
    read_only=True,
)
def file_read_tracked(file_path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read file content with line numbers. Tracks the file for edit validation."""
    abs_path = os.path.abspath(file_path)
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        mark_file_read(abs_path)
        total = len(lines)
        selected = lines[offset : offset + limit]
        result = []
        for i, line in enumerate(selected, start=offset + 1):
            result.append(f"{i}\t{line.rstrip()}")
        header = f"[{abs_path}] ({total} lines total)"
        return header + "\n" + "\n".join(result)
    except (IOError, OSError) as e:
        return f"Error: {e}"


@tool(
    description="Edit a file by replacing an exact string match. "
    "old_string must be unique in the file. File must be read first.",
    read_only=False,
)
def file_edit(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    """Replace an exact string in a file.

    1. Check file was previously read (via mark_file_read tracking).
    2. Read file content.
    3. If not replace_all: verify old_string appears exactly once.
    4. Perform replacement.
    5. Write back.
    """
    abs_path = os.path.abspath(file_path)

    # Enforce read-before-edit
    if abs_path not in _read_files:
        return (
            f"Error: file_edit requires reading the file first. "
            f"Use file_read on '{file_path}' before editing."
        )

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (IOError, OSError) as e:
        return f"Error reading file: {e}"

    if old_string == new_string:
        return "Error: old_string and new_string are identical."

    count = content.count(old_string)

    if count == 0:
        return f"Error: old_string not found in {file_path}."

    if not replace_all and count > 1:
        return (
            f"Error: old_string found {count} times in {file_path}. "
            "Provide more context to make it unique, or set replace_all=True."
        )

    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)

    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except (IOError, OSError) as e:
        return f"Error writing file: {e}"

    replacements = count if replace_all else 1
    return f"Successfully edited {file_path}: {replacements} replacement(s) made."
