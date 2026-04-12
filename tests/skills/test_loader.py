from pathlib import Path

import pytest

from breadmind.skills.loader import BundleLoader


FIXTURE = Path(__file__).parent / "fixtures" / "sample_bundle"


def test_load_returns_bundle():
    loader = BundleLoader()
    bundle = loader.load(FIXTURE)
    assert bundle.name == "sample-skill"
    assert bundle.priority == 10
    assert bundle.depends_on == ["base-skill"]
    assert bundle.bundle_path == str(FIXTURE)


def test_load_detects_reference_files():
    loader = BundleLoader()
    bundle = loader.load(FIXTURE)
    assert set(bundle.reference_markers) == {
        "references/overview.md",
        "references/detail.md",
    }


def test_load_missing_skill_md_raises(tmp_path):
    loader = BundleLoader()
    with pytest.raises(FileNotFoundError):
        loader.load(tmp_path)


def test_load_directory_without_references_ok(tmp_path):
    (tmp_path / "SKILL.md").write_text(
        "---\nname: bare\ndescription: no refs\n---\nbody",
    )
    loader = BundleLoader()
    bundle = loader.load(tmp_path)
    assert bundle.name == "bare"
    assert bundle.reference_markers == []
