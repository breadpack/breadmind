"""플러그인 semver 버전 제약 파싱 및 검증."""
from __future__ import annotations

import re
from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


@dataclass(frozen=True, slots=True)
class VersionConstraint:
    """파싱된 의존성 제약."""

    name: str
    specifier: str  # 예: ">=1.0,<2.0" 또는 "" (버전 무관)


# 이름 뒤에 버전 specifier가 오는 패턴 (>=, <=, !=, ~=, ==, > , < 시작)
_DEP_RE = re.compile(r"^([A-Za-z0-9_\-]+)((?:[><=!~]=?|~=).+)?$")


def parse_dependency(dep_str: str) -> VersionConstraint:
    """의존성 문자열을 VersionConstraint로 파싱.

    Examples:
        "auth"          → VersionConstraint(name="auth", specifier="")
        "auth>=1.0"     → VersionConstraint(name="auth", specifier=">=1.0")
        "auth>=1.0,<2.0" → VersionConstraint(name="auth", specifier=">=1.0,<2.0")
    """
    dep_str = dep_str.strip()
    m = _DEP_RE.match(dep_str)
    if not m:
        return VersionConstraint(name=dep_str, specifier="")
    name = m.group(1)
    specifier = m.group(2) or ""
    return VersionConstraint(name=name, specifier=specifier)


def check_version(version: str, specifier: str) -> bool:
    """버전이 specifier를 만족하는지 확인.

    빈 specifier는 항상 True를 반환한다.
    """
    if not specifier:
        return True
    try:
        return Version(version) in SpecifierSet(specifier)
    except (InvalidVersion, InvalidSpecifier):
        return False


def validate_dependencies(
    plugins: dict[str, "PluginManifest"],  # noqa: F821
) -> list[str]:
    """모든 플러그인의 의존성을 검증하고 에러 메시지 리스트를 반환.

    반환되는 에러 유형:
    - 존재하지 않는 플러그인 의존
    - 버전 제약 불일치
    """
    # provides → plugin name 매핑
    provides_map: dict[str, str] = {}
    for name, manifest in plugins.items():
        for p in manifest.provides:
            provides_map[p] = name

    errors: list[str] = []
    for name, manifest in plugins.items():
        for dep_str in manifest.depends_on:
            constraint = parse_dependency(dep_str)
            provider_name = provides_map.get(constraint.name, constraint.name)

            if provider_name not in plugins:
                errors.append(
                    f"Plugin '{name}' depends on '{constraint.name}' "
                    f"which is not installed"
                )
                continue

            if constraint.specifier:
                provider_version = plugins[provider_name].version
                if not check_version(provider_version, constraint.specifier):
                    errors.append(
                        f"Plugin '{name}' requires '{constraint.name}"
                        f"{constraint.specifier}' but found version "
                        f"'{provider_version}'"
                    )

    return errors
