"""Tests for OS-specific administration skills."""
import pytest
from unittest.mock import AsyncMock
from breadmind.skills.os_skills import (
    LINUX_SKILL,
    WINDOWS_SKILL,
    MACOS_SKILL,
    get_os_skill,
    get_all_os_skills,
    register_os_skills,
    build_linux_prompt,
)


class TestOsSkillDefinitions:
    def test_linux_skill_has_required_fields(self):
        assert LINUX_SKILL.name == "linux_admin"
        assert LINUX_SKILL.source == "builtin"
        assert len(LINUX_SKILL.trigger_keywords) > 0
        assert "systemctl" in LINUX_SKILL.prompt_template

    def test_windows_skill_has_required_fields(self):
        assert WINDOWS_SKILL.name == "windows_admin"
        assert WINDOWS_SKILL.source == "builtin"
        assert "PowerShell" in WINDOWS_SKILL.prompt_template
        assert "winget" in WINDOWS_SKILL.prompt_template

    def test_macos_skill_has_required_fields(self):
        assert MACOS_SKILL.name == "macos_admin"
        assert MACOS_SKILL.source == "builtin"
        assert "brew" in MACOS_SKILL.prompt_template
        assert "launchctl" in MACOS_SKILL.prompt_template

    def test_all_skills_have_steps(self):
        for skill in [LINUX_SKILL, WINDOWS_SKILL, MACOS_SKILL]:
            assert len(skill.steps) > 0, f"{skill.name} has no steps"

    def test_all_skills_have_korean_keywords(self):
        """Skills should be discoverable via Korean queries too."""
        for skill in [LINUX_SKILL, WINDOWS_SKILL, MACOS_SKILL]:
            korean = [kw for kw in skill.trigger_keywords if any('\uac00' <= c <= '\ud7a3' for c in kw)]
            assert len(korean) > 0, f"{skill.name} has no Korean trigger keywords"


class TestLinuxDistroTailoring:
    """Test that Linux skill prompt is customized per distro."""

    def test_debian_prompt_has_apt(self):
        prompt = build_linux_prompt(["apt"])
        assert "apt update" in prompt
        assert "apt install" in prompt
        assert "dnf" not in prompt
        assert "pacman" not in prompt

    def test_rhel_prompt_has_dnf(self):
        prompt = build_linux_prompt(["dnf"])
        assert "dnf install" in prompt
        assert "apt update" not in prompt
        assert "pacman" not in prompt

    def test_arch_prompt_has_pacman(self):
        prompt = build_linux_prompt(["pacman"])
        assert "pacman -S" in prompt
        assert "apt update" not in prompt
        assert "dnf" not in prompt

    def test_alpine_prompt_has_apk(self):
        prompt = build_linux_prompt(["apk"])
        assert "apk add" in prompt
        assert "apt update" not in prompt

    def test_suse_prompt_has_zypper(self):
        prompt = build_linux_prompt(["zypper"])
        assert "zypper install" in prompt
        assert "apt update" not in prompt

    def test_multiple_managers_included(self):
        """apt + snap should include both sections."""
        prompt = build_linux_prompt(["apt", "snap"])
        assert "apt update" in prompt
        assert "snap install" in prompt
        assert "dnf" not in prompt

    def test_no_managers_gives_generic(self):
        prompt = build_linux_prompt(None)
        assert "Debian/Ubuntu" in prompt
        assert "RHEL/Fedora" in prompt

    def test_unknown_manager_gives_generic(self):
        prompt = build_linux_prompt(["nix"])
        assert "Debian/Ubuntu" in prompt  # Fallback to generic

    def test_common_sections_always_present(self):
        """Service, process, network etc. should always be included."""
        for pms in [["apt"], ["dnf"], ["pacman"], None]:
            prompt = build_linux_prompt(pms)
            assert "systemctl" in prompt
            assert "ps aux" in prompt
            assert "ip addr" in prompt
            assert "df -h" in prompt
            assert "docker" in prompt.lower()


class TestOsSkillSelection:
    def test_get_linux_skill(self):
        assert get_os_skill("Linux").name == "linux_admin"

    def test_get_windows_skill(self):
        assert get_os_skill("Windows").name == "windows_admin"

    def test_get_macos_skill(self):
        assert get_os_skill("Darwin").name == "macos_admin"

    def test_get_unknown_os_returns_none(self):
        assert get_os_skill("FreeBSD") is None

    def test_auto_detect_os(self):
        assert get_os_skill() is not None

    def test_get_all_returns_three(self):
        skills = get_all_os_skills()
        assert len(skills) == 3
        assert {s.name for s in skills} == {"linux_admin", "windows_admin", "macos_admin"}


class TestOsSkillRegistration:
    @pytest.mark.asyncio
    async def test_register_adds_skill(self):
        store = AsyncMock()
        store.get_skill.return_value = None
        store.add_skill = AsyncMock()

        await register_os_skills(store, os_name="Linux")

        store.add_skill.assert_called_once()
        assert store.add_skill.call_args.kwargs["name"] == "linux_admin"

    @pytest.mark.asyncio
    async def test_register_linux_with_package_managers(self):
        """Should use tailored prompt when package_managers provided."""
        store = AsyncMock()
        store.get_skill.return_value = None
        store.add_skill = AsyncMock()

        await register_os_skills(store, os_name="Linux", package_managers=["apt", "snap"])

        call_kwargs = store.add_skill.call_args.kwargs
        assert "apt update" in call_kwargs["prompt_template"]
        assert "snap install" in call_kwargs["prompt_template"]
        assert "dnf" not in call_kwargs["prompt_template"]

    @pytest.mark.asyncio
    async def test_register_skips_if_already_exists(self):
        store = AsyncMock()
        store.get_skill.return_value = LINUX_SKILL
        store.add_skill = AsyncMock()

        await register_os_skills(store, os_name="Linux")

        store.add_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_skips_unknown_os(self):
        store = AsyncMock()
        store.add_skill = AsyncMock()

        await register_os_skills(store, os_name="FreeBSD")

        store.add_skill.assert_not_called()
