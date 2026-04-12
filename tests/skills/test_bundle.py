from breadmind.skills.bundle import SkillBundle, parse_skill_md


SAMPLE = """\
---
name: refactor-helper
description: Guide a Python refactor with test-first discipline
priority: 50
depends_on:
  - test-runner
tags: [python, refactor]
---

# Refactor helper

Start with a failing test.

See @references/overview.md for the full workflow.
"""


def test_parse_skill_md_extracts_frontmatter():
    bundle = parse_skill_md(SAMPLE, bundle_path="/tmp/b")
    assert bundle.name == "refactor-helper"
    assert bundle.description.startswith("Guide a Python")
    assert bundle.priority == 50
    assert bundle.depends_on == ["test-runner"]
    assert bundle.tags == ["python", "refactor"]
    assert "failing test" in bundle.body
    assert bundle.bundle_path == "/tmp/b"


def test_parse_detects_reference_markers():
    bundle = parse_skill_md(SAMPLE, bundle_path="/tmp/b")
    assert "references/overview.md" in bundle.reference_markers


def test_parse_missing_frontmatter_returns_minimal_bundle():
    bundle = parse_skill_md("just body, no frontmatter", bundle_path="/tmp/b")
    assert bundle.name == ""
    assert bundle.body == "just body, no frontmatter"
    assert bundle.depends_on == []


def test_parse_priority_defaults_to_zero():
    md = "---\nname: x\ndescription: y\n---\nbody"
    bundle = parse_skill_md(md, bundle_path="/tmp/b")
    assert bundle.priority == 0
