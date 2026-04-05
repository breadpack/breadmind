"""Tests for cross-format plugin bundle loader."""
from __future__ import annotations
import json
import os

from breadmind.plugins.bundle_loader import BundleLoader, BundleFormat


def test_detect_native_format(tmp_path):
    (tmp_path / "plugin.json").write_text('{"name": "test"}')
    loader = BundleLoader()
    assert loader.detect_format(str(tmp_path)) == BundleFormat.NATIVE


def test_detect_claude_format(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text('{}')
    loader = BundleLoader()
    assert loader.detect_format(str(tmp_path)) == BundleFormat.CLAUDE


def test_detect_codex_format(tmp_path):
    codex_dir = tmp_path / ".codex-plugin"
    codex_dir.mkdir()
    (codex_dir / "plugin.json").write_text('{"name": "codex-test"}')
    loader = BundleLoader()
    assert loader.detect_format(str(tmp_path)) == BundleFormat.CODEX


def test_detect_cursor_format(tmp_path):
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    (cursor_dir / "rules").write_text("rule1")
    loader = BundleLoader()
    assert loader.detect_format(str(tmp_path)) == BundleFormat.CURSOR


def test_detect_unknown(tmp_path):
    loader = BundleLoader()
    assert loader.detect_format(str(tmp_path)) is None


def test_load_claude_bundle(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "mcpServers": {"server1": {}, "server2": {}}
    }))
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()
    (commands_dir / "deploy.md").write_text("# Deploy")
    (commands_dir / "status.md").write_text("# Status")

    loader = BundleLoader()
    bundle = loader.load_bundle(str(tmp_path))
    assert bundle is not None
    assert bundle.format == BundleFormat.CLAUDE
    assert set(bundle.skills) == {"deploy", "status"}
    assert set(bundle.mcp_servers) == {"server1", "server2"}


def test_load_native_bundle(tmp_path):
    (tmp_path / "plugin.json").write_text(json.dumps({
        "name": "my-plugin",
        "x-breadmind": {
            "tools": [{"name": "tool1"}, {"name": "tool2"}]
        }
    }))
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "build.md").write_text("# Build")

    loader = BundleLoader()
    bundle = loader.load_bundle(str(tmp_path))
    assert bundle is not None
    assert bundle.format == BundleFormat.NATIVE
    assert bundle.name == "my-plugin"
    assert set(bundle.tools) == {"tool1", "tool2"}
    assert "build" in bundle.skills
