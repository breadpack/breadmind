from pathlib import Path

from breadmind.core.skill_store import SkillStore


FIXTURE = Path(__file__).parent / "fixtures" / "sample_bundle"


async def test_install_bundle_creates_skill_with_metadata():
    store = SkillStore(db=None, tracker=None)
    skill = await store.install_bundle(FIXTURE)
    assert skill.name == "sample-skill"
    assert skill.priority == 10
    assert skill.depends_on == ["base-skill"]
    assert skill.bundle_path == str(FIXTURE)
    assert "references/overview.md" in skill.reference_markers
    assert "references/detail.md" in skill.reference_markers


async def test_install_bundle_replaces_existing():
    store = SkillStore(db=None, tracker=None)
    await store.install_bundle(FIXTURE)
    # Installing again should succeed (replace)
    skill = await store.install_bundle(FIXTURE)
    assert skill.name == "sample-skill"
