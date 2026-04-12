"""Tests for skill progressive disclosure."""
import pytest
from breadmind.core.skill_store import SkillStore


@pytest.fixture
def store():
    return SkillStore()


async def test_load_frontmatter_only(store):
    skill = await store.load_frontmatter_only(
        name="deploy", description="Deploy to production",
        file_path="/tmp/nonexistent.md",
        trigger_keywords=["deploy", "production"],
    )
    assert skill.name == "deploy"
    assert skill.description == "Deploy to production"
    assert skill.prompt_template == ""
    assert skill.frontmatter_only is True
    assert skill.full_loaded is False
    # Should be retrievable
    loaded = await store.get_skill("deploy")
    assert loaded is skill


async def test_load_full_on_demand(tmp_path, store):
    skill_file = tmp_path / "test_skill.md"
    skill_file.write_text("---\nname: test\n---\nThis is the full prompt template content.")

    await store.load_frontmatter_only(
        name="test", description="A test skill",
        file_path=str(skill_file),
    )

    # Initially no prompt_template
    skill = await store.get_skill("test")
    assert skill.prompt_template == ""

    # Load full content
    skill = await store.load_full("test")
    assert skill is not None
    assert skill.prompt_template == "This is the full prompt template content."
    assert skill.full_loaded is True
    assert skill.frontmatter_only is False


async def test_get_frontmatter_list(store):
    await store.load_frontmatter_only("skill_a", "Description A", "/a.md", ["kw1"])
    await store.load_frontmatter_only("skill_b", "Description B", "/b.md", ["kw2", "kw3"])

    fl = store.get_frontmatter_list()
    assert len(fl) == 2
    names = {item["name"] for item in fl}
    assert "skill_a" in names
    assert "skill_b" in names
    # Should have keywords
    for item in fl:
        if item["name"] == "skill_b":
            assert "kw2" in item["keywords"]


async def test_full_loaded_flag(tmp_path, store):
    skill_file = tmp_path / "already.md"
    skill_file.write_text("---\nname: x\n---\nContent here.")

    await store.load_frontmatter_only("x", "X skill", str(skill_file))
    skill = await store.load_full("x")
    assert skill.full_loaded is True

    # Calling load_full again should return immediately (no re-read)
    skill2 = await store.load_full("x")
    assert skill2 is skill
    assert skill2.full_loaded is True
