from __future__ import annotations

from pathlib import Path

from breadmind.skills.bundle import SkillBundle, parse_skill_md


class BundleLoader:
    """Load a skill bundle from a directory on disk."""

    def load(self, directory: Path | str) -> SkillBundle:
        path = Path(directory)
        skill_md = path / "SKILL.md"
        if not skill_md.is_file():
            raise FileNotFoundError(f"SKILL.md not found in {path}")
        content = skill_md.read_text(encoding="utf-8")
        return parse_skill_md(content, bundle_path=str(path))

    def resolve_reference(self, bundle: SkillBundle, marker: str) -> str:
        """Read a reference file relative to the bundle path.

        `marker` is of the form ``references/foo.md``. Returns the file
        contents, or an empty string on miss.
        """
        if not bundle.bundle_path:
            return ""
        path = Path(bundle.bundle_path) / marker
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
