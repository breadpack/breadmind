"""Tests for domain-specific administration skills."""
import pytest
from unittest.mock import AsyncMock, patch
from breadmind.skills.domain_skills import (
    ALL_DOMAIN_SKILLS,
    WEBSERVER_SKILL,
    DATABASE_SKILL,
    SECURITY_SKILL,
    VIRTUALIZATION_SKILL,
    MONITORING_SKILL,
    CICD_SKILL,
    STORAGE_SKILL,
    NETWORK_INFRA_SKILL,
    detect_domains,
    register_domain_skills,
)


class TestSkillDefinitions:
    """All domain skills must have required fields and content."""

    @pytest.mark.parametrize("skill", ALL_DOMAIN_SKILLS.values(), ids=lambda s: s.name)
    def test_has_required_fields(self, skill):
        assert skill.name
        assert skill.description
        assert len(skill.prompt_template) > 100
        assert len(skill.trigger_keywords) >= 5
        assert skill.source == "builtin"
        assert len(skill.steps) > 0

    @pytest.mark.parametrize("skill", ALL_DOMAIN_SKILLS.values(), ids=lambda s: s.name)
    def test_has_korean_keywords(self, skill):
        """Each skill should be discoverable via Korean queries."""
        korean = [kw for kw in skill.trigger_keywords if any('\uac00' <= c <= '\ud7a3' for c in kw)]
        assert len(korean) > 0, f"{skill.name} has no Korean trigger keywords"

    def test_all_eight_domains_present(self):
        assert len(ALL_DOMAIN_SKILLS) == 8
        expected = {
            "webserver_admin", "database_admin", "security_admin",
            "virtualization_admin", "monitoring_admin", "cicd_admin",
            "storage_admin", "network_infra_admin",
        }
        assert set(ALL_DOMAIN_SKILLS.keys()) == expected


class TestSkillContent:
    """Verify key domain knowledge is present in each skill."""

    def test_webserver_has_nginx_and_apache(self):
        assert "nginx -t" in WEBSERVER_SKILL.prompt_template
        assert "apachectl" in WEBSERVER_SKILL.prompt_template or "httpd" in WEBSERVER_SKILL.prompt_template

    def test_database_has_mysql_and_postgres(self):
        assert "mysqldump" in DATABASE_SKILL.prompt_template
        assert "pg_dump" in DATABASE_SKILL.prompt_template
        assert "redis-cli" in DATABASE_SKILL.prompt_template

    def test_security_has_certbot_and_firewall(self):
        assert "certbot" in SECURITY_SKILL.prompt_template
        assert "ufw" in SECURITY_SKILL.prompt_template
        assert "fail2ban" in SECURITY_SKILL.prompt_template

    def test_virtualization_has_proxmox_and_kvm(self):
        assert "qm list" in VIRTUALIZATION_SKILL.prompt_template
        assert "virsh" in VIRTUALIZATION_SKILL.prompt_template

    def test_monitoring_has_prometheus_and_grafana(self):
        assert "promtool" in MONITORING_SKILL.prompt_template
        assert "grafana-cli" in MONITORING_SKILL.prompt_template
        assert "PromQL" in MONITORING_SKILL.prompt_template

    def test_cicd_has_jenkins_and_github(self):
        assert "jenkins" in CICD_SKILL.prompt_template.lower()
        assert "gh run" in CICD_SKILL.prompt_template

    def test_storage_has_zfs_and_lvm(self):
        assert "zpool" in STORAGE_SKILL.prompt_template
        assert "lvs" in STORAGE_SKILL.prompt_template
        assert "mdadm" in STORAGE_SKILL.prompt_template

    def test_network_has_dns_and_vpn(self):
        assert "named-checkconf" in NETWORK_INFRA_SKILL.prompt_template or "BIND" in NETWORK_INFRA_SKILL.prompt_template
        assert "wireguard" in NETWORK_INFRA_SKILL.prompt_template.lower()
        assert "haproxy" in NETWORK_INFRA_SKILL.prompt_template.lower()


class TestDetection:
    @patch("shutil.which")
    def test_detect_nginx(self, mock_which):
        mock_which.side_effect = lambda exe: "/usr/sbin/nginx" if exe == "nginx" else None
        domains = detect_domains()
        names = [d.skill_name for d in domains]
        assert "webserver_admin" in names
        ws = next(d for d in domains if d.skill_name == "webserver_admin")
        assert "nginx" in ws.detected_tools

    @patch("shutil.which")
    def test_detect_multiple_domains(self, mock_which):
        found = {"nginx", "psql", "openssl", "gh"}
        mock_which.side_effect = lambda exe: f"/usr/bin/{exe}" if exe in found else None
        domains = detect_domains()
        names = {d.skill_name for d in domains}
        assert "webserver_admin" in names
        assert "database_admin" in names
        assert "security_admin" in names
        assert "cicd_admin" in names

    @patch("shutil.which")
    def test_detect_nothing(self, mock_which):
        mock_which.return_value = None
        domains = detect_domains()
        assert len(domains) == 0


class TestRegistration:
    @pytest.mark.asyncio
    @patch("breadmind.skills.domain_skills.detect_domains")
    async def test_register_detected_skills(self, mock_detect):
        from breadmind.skills.domain_skills import DetectedDomain
        mock_detect.return_value = [
            DetectedDomain(skill_name="webserver_admin", detected_tools=["nginx"]),
            DetectedDomain(skill_name="database_admin", detected_tools=["psql"]),
        ]

        store = AsyncMock()
        store.get_skill.return_value = None
        store.add_skill = AsyncMock()

        await register_domain_skills(store)

        assert store.add_skill.call_count == 2
        registered = {call.kwargs["name"] for call in store.add_skill.call_args_list}
        assert registered == {"webserver_admin", "database_admin"}

    @pytest.mark.asyncio
    @patch("breadmind.skills.domain_skills.detect_domains")
    async def test_skip_already_registered(self, mock_detect):
        from breadmind.skills.domain_skills import DetectedDomain
        mock_detect.return_value = [
            DetectedDomain(skill_name="webserver_admin", detected_tools=["nginx"]),
        ]

        store = AsyncMock()
        store.get_skill.return_value = WEBSERVER_SKILL  # Already exists
        store.add_skill = AsyncMock()

        await register_domain_skills(store)

        store.add_skill.assert_not_called()

    @pytest.mark.asyncio
    @patch("breadmind.skills.domain_skills.detect_domains")
    async def test_no_detection_no_registration(self, mock_detect):
        mock_detect.return_value = []

        store = AsyncMock()
        store.add_skill = AsyncMock()

        await register_domain_skills(store)

        store.add_skill.assert_not_called()
