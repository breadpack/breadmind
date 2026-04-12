from __future__ import annotations

from breadmind.skills.bundle import SkillBundle
from breadmind.skills.loader import BundleLoader


class ReferenceResolver:
    """Substitute @references/* markers in a skill body with file contents.

    Per-resolver in-memory cache so repeated invocations within one
    session do not re-read files.
    """

    def __init__(self, loader: BundleLoader) -> None:
        self._loader = loader
        self._cache: dict[tuple[str, str], str] = {}

    def resolve(self, bundle: SkillBundle) -> str:
        body = bundle.body
        for marker in bundle.reference_markers:
            placeholder = f"@{marker}"
            key = (bundle.bundle_path, marker)
            if key in self._cache:
                content = self._cache[key]
            else:
                content = self._loader.resolve_reference(bundle, marker)
                self._cache[key] = content
            if not content:
                replacement = f"@{marker} [reference missing]"
            else:
                replacement = content
            body = body.replace(placeholder, replacement)
        return body

    def clear_cache(self) -> None:
        self._cache.clear()
