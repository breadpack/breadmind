"""JSON Patch (RFC 6902) diff/apply for UISpec."""
from __future__ import annotations

from typing import Any

import jsonpatch

from breadmind.sdui.spec import UISpec


def diff_specs(old: UISpec, new: UISpec) -> list[dict[str, Any]]:
    """Compute a JSON Patch (RFC 6902) between two UISpecs."""
    patch = jsonpatch.JsonPatch.from_diff(old.to_dict(), new.to_dict())
    return list(patch.patch)


def apply_patch(doc: dict[str, Any], patch: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply a JSON Patch to a UISpec dict, returning the resulting document."""
    return jsonpatch.apply_patch(doc, patch)
