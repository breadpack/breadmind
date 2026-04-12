"""플러그인 semver 버전 제약 테스트."""

from breadmind.core.plugin import PluginManifest
from breadmind.core.version import (
    VersionConstraint,
    check_version,
    parse_dependency,
    validate_dependencies,
)


# --- parse_dependency ---


def test_parse_dependency_name_only():
    result = parse_dependency("auth")
    assert result == VersionConstraint(name="auth", specifier="")


def test_parse_dependency_with_version():
    result = parse_dependency("auth>=1.0")
    assert result == VersionConstraint(name="auth", specifier=">=1.0")


def test_parse_dependency_range():
    result = parse_dependency("auth>=1.0,<2.0")
    assert result == VersionConstraint(name="auth", specifier=">=1.0,<2.0")


# --- check_version ---


def test_check_version_satisfied():
    assert check_version("1.5.0", ">=1.0,<2.0") is True


def test_check_version_not_satisfied():
    assert check_version("2.1.0", ">=1.0,<2.0") is False


def test_check_version_empty_specifier():
    assert check_version("0.0.1", "") is True
    assert check_version("999.0.0", "") is True


# --- validate_dependencies ---


def test_validate_dependencies_all_ok():
    plugins = {
        "auth": PluginManifest(name="auth", version="1.5.0", provides=["auth"]),
        "api": PluginManifest(
            name="api", version="2.0.0", depends_on=["auth>=1.0,<2.0"],
        ),
    }
    errors = validate_dependencies(plugins)
    assert errors == []


def test_validate_dependencies_version_mismatch():
    plugins = {
        "auth": PluginManifest(name="auth", version="2.5.0", provides=["auth"]),
        "api": PluginManifest(
            name="api", version="1.0.0", depends_on=["auth>=1.0,<2.0"],
        ),
    }
    errors = validate_dependencies(plugins)
    assert len(errors) == 1
    assert "auth" in errors[0]
    assert "2.5.0" in errors[0]


def test_validate_dependencies_missing_plugin():
    plugins = {
        "api": PluginManifest(
            name="api", version="1.0.0", depends_on=["missing-plugin"],
        ),
    }
    errors = validate_dependencies(plugins)
    assert len(errors) == 1
    assert "missing-plugin" in errors[0]
    assert "not installed" in errors[0]


def test_backward_compatible():
    """기존 이름만 있는 depends_on도 정상 동작해야 한다."""
    plugins = {
        "auth": PluginManifest(name="auth", version="1.0.0", provides=["auth"]),
        "api": PluginManifest(
            name="api", version="1.0.0", depends_on=["auth"],
        ),
    }
    errors = validate_dependencies(plugins)
    assert errors == []
