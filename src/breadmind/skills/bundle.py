from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


_REF_RE = re.compile(r"@(references/[\w\-./]+)")
_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class SkillBundle:
    name: str = ""
    description: str = ""
    body: str = ""
    priority: int = 0
    depends_on: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    reference_markers: list[str] = field(default_factory=list)
    bundle_path: str = ""
    version: str = ""
    author: str = ""

    @property
    def references(self) -> list[str]:
        return list(self.reference_markers)


def _parse_yaml_like(text: str) -> dict[str, Any]:
    if yaml is not None:
        try:
            out = yaml.safe_load(text)
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    data: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - ") and current_list_key:
            data.setdefault(current_list_key, []).append(line[4:].strip())
            continue
        if ":" in line:
            key, _, rest = line.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest == "":
                current_list_key = key
                data[key] = []
            else:
                current_list_key = None
                if rest.startswith("[") and rest.endswith("]"):
                    data[key] = [
                        x.strip().strip("'\"") for x in rest[1:-1].split(",") if x.strip()
                    ]
                elif rest.isdigit():
                    data[key] = int(rest)
                else:
                    data[key] = rest.strip("'\"")
    return data


def parse_skill_md(content: str, *, bundle_path: str = "") -> SkillBundle:
    m = _FRONT_RE.match(content)
    if not m:
        return SkillBundle(body=content, bundle_path=bundle_path)

    frontmatter_raw, body = m.group(1), m.group(2)
    meta = _parse_yaml_like(frontmatter_raw)

    bundle = SkillBundle(
        name=str(meta.get("name", "")),
        description=str(meta.get("description", "")),
        body=body.strip("\n"),
        priority=int(meta.get("priority", 0) or 0),
        depends_on=list(meta.get("depends_on") or []),
        tags=list(meta.get("tags") or []),
        trigger_keywords=list(meta.get("trigger_keywords") or []),
        version=str(meta.get("version", "")),
        author=str(meta.get("author", "")),
        bundle_path=bundle_path,
    )
    bundle.reference_markers = sorted(set(_REF_RE.findall(body)))
    return bundle
