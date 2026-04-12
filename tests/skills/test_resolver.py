from pathlib import Path

from breadmind.skills.loader import BundleLoader
from breadmind.skills.resolver import ReferenceResolver


FIXTURE = Path(__file__).parent / "fixtures" / "sample_bundle"


def test_resolve_substitutes_all_markers():
    loader = BundleLoader()
    bundle = loader.load(FIXTURE)
    resolver = ReferenceResolver(loader)
    resolved = resolver.resolve(bundle)
    assert "@references/overview.md" not in resolved
    assert "@references/detail.md" not in resolved
    assert "High-level context" in resolved
    assert "Step-by-step detail" in resolved


def test_resolve_unknown_marker_keeps_marker_with_note():
    from breadmind.skills.bundle import SkillBundle
    bundle = SkillBundle(
        name="t", body="See @references/missing.md for more.", bundle_path=str(FIXTURE),
    )
    bundle.reference_markers = ["references/missing.md"]
    loader = BundleLoader()
    resolver = ReferenceResolver(loader)
    resolved = resolver.resolve(bundle)
    assert "missing.md" in resolved
    assert "[reference missing]" in resolved or "@references/missing.md" in resolved


def test_resolve_caches_reads(tmp_path):
    (tmp_path / "SKILL.md").write_text(
        "---\nname: x\ndescription: y\n---\nsee @references/a.md",
    )
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "a.md").write_text("AAA")
    loader = BundleLoader()
    bundle = loader.load(tmp_path)
    bundle.reference_markers = ["references/a.md"]

    resolver = ReferenceResolver(loader)
    _ = resolver.resolve(bundle)
    (refs / "a.md").write_text("BBB")
    resolved2 = resolver.resolve(bundle)
    assert "AAA" in resolved2
