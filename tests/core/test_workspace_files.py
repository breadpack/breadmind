"""Tests for the structured workspace file system."""
from __future__ import annotations

import os

import pytest

from breadmind.core.workspace_files import WorkspaceFileManager, WORKSPACE_FILES


@pytest.fixture
def workspace_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def populated_dir(tmp_path):
    """Create a workspace dir with some files."""
    (tmp_path / "SOUL.md").write_text("I am a helpful assistant.", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Rule 1: Be kind.", encoding="utf-8")
    (tmp_path / "TOOLS.md").write_text("tool: shell_exec", encoding="utf-8")
    return str(tmp_path)


async def test_load_from_directory(populated_dir: str):
    mgr = WorkspaceFileManager(populated_dir)
    soul = mgr.get_file("SOUL.md")
    assert soul is not None
    assert soul.content == "I am a helpful assistant."


async def test_get_injection_blocks(populated_dir: str):
    mgr = WorkspaceFileManager(populated_dir)
    blocks = mgr.get_injection_blocks(mode="always")
    assert len(blocks) >= 3
    names = [b["file_name"] for b in blocks]
    assert "SOUL.md" in names
    assert "AGENTS.md" in names
    assert "TOOLS.md" in names


async def test_update_file(workspace_dir: str):
    mgr = WorkspaceFileManager(workspace_dir)
    result = mgr.update_file("SOUL.md", "New personality")
    assert result is True
    wf = mgr.get_file("SOUL.md")
    assert wf is not None
    assert wf.content == "New personality"
    # Verify written to disk
    path = os.path.join(workspace_dir, "SOUL.md")
    assert os.path.exists(path)
    with open(path, 'r', encoding='utf-8') as f:
        assert f.read() == "New personality"


async def test_max_chars_enforced(workspace_dir: str):
    mgr = WorkspaceFileManager(workspace_dir)
    identity = mgr.get_file("IDENTITY.md")
    assert identity is not None
    long_text = "x" * 5000
    mgr.update_file("IDENTITY.md", long_text)
    assert len(identity.content) <= identity.max_chars


async def test_total_max_chars_limit(tmp_path):
    """Total injection should respect total_max_chars."""
    for wf_def in WORKSPACE_FILES:
        if wf_def.inject_mode == "always":
            (tmp_path / wf_def.name).write_text("a" * 3000, encoding="utf-8")
    mgr = WorkspaceFileManager(str(tmp_path), total_max_chars=5000)
    blocks = mgr.get_injection_blocks(mode="always")
    total = sum(len(b["content"]) for b in blocks)
    # The total injected content should not exceed total_max_chars
    # (content includes the "[NAME.md]\n" prefix so may be slightly over raw content)
    assert total <= 5000 + len(WORKSPACE_FILES) * 20  # allow for prefix overhead


async def test_reload(populated_dir: str):
    mgr = WorkspaceFileManager(populated_dir)
    assert mgr.get_file("SOUL.md").content == "I am a helpful assistant."
    # Modify file on disk
    with open(os.path.join(populated_dir, "SOUL.md"), 'w', encoding='utf-8') as f:
        f.write("Updated personality")
    mgr.reload()
    assert mgr.get_file("SOUL.md").content == "Updated personality"


async def test_list_files(populated_dir: str):
    mgr = WorkspaceFileManager(populated_dir)
    files = mgr.list_files()
    assert len(files) == len(WORKSPACE_FILES)
    names = {f["name"] for f in files}
    assert "SOUL.md" in names
    assert "HEARTBEAT.md" in names


async def test_on_demand_not_injected_by_default(tmp_path):
    (tmp_path / "HEARTBEAT.md").write_text("heartbeat data", encoding="utf-8")
    mgr = WorkspaceFileManager(str(tmp_path))
    blocks = mgr.get_injection_blocks(mode="always")
    file_names = [b["file_name"] for b in blocks]
    assert "HEARTBEAT.md" not in file_names


async def test_missing_files_empty_content(workspace_dir: str):
    mgr = WorkspaceFileManager(workspace_dir)
    soul = mgr.get_file("SOUL.md")
    assert soul is not None
    assert soul.content == ""
