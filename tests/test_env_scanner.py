"""Tests for environment scanner."""
import pytest
from breadmind.core.env_scanner import scan_environment, store_scan_in_memory, ScanResult
from breadmind.memory.episodic import EpisodicMemory
from breadmind.memory.semantic import SemanticMemory


class TestScanResult:
    def test_to_memory_text(self):
        scan = ScanResult(
            hostname="test-host",
            os_name="Windows",
            os_version="11",
            os_arch="AMD64",
            cpu_info="Intel i7",
            cpu_cores=8,
            memory_total_gb=32.0,
            memory_available_gb=16.0,
            disks=[{"drive": "C:", "total_gb": 500, "free_gb": 200, "percent_used": 60}],
            installed_tools={"git": "2.40", "python": "3.12"},
            docker_version="24.0.0",
            ip_addresses=["192.168.1.100"],
        )
        text = scan.to_memory_text()
        assert "test-host" in text
        assert "Intel i7" in text
        assert "C:" in text
        assert "git" in text
        assert "Docker" in text

    def test_to_keywords(self):
        scan = ScanResult(
            hostname="myhost",
            os_name="Linux",
            installed_tools={"docker": "24.0", "git": "2.40"},
            ip_addresses=["10.0.0.1"],
        )
        kws = scan.to_keywords()
        assert "myhost" in kws
        assert "docker" in kws
        assert "10.0.0.1" in kws


class TestScanEnvironment:
    @pytest.mark.asyncio
    async def test_scan_returns_basic_info(self):
        scan = await scan_environment()
        assert scan.hostname != ""
        assert scan.os_name != ""
        assert scan.cpu_cores > 0

    @pytest.mark.asyncio
    async def test_scan_detects_memory(self):
        scan = await scan_environment()
        assert scan.memory_total_gb > 0

    @pytest.mark.asyncio
    async def test_scan_detects_disks(self):
        scan = await scan_environment()
        assert len(scan.disks) > 0

    @pytest.mark.asyncio
    async def test_scan_detects_tools(self):
        scan = await scan_environment()
        # At minimum python and git should be found
        assert "python" in scan.installed_tools or "git" in scan.installed_tools


class TestStoreInMemory:
    @pytest.mark.asyncio
    async def test_stores_pinned_note(self):
        em = EpisodicMemory()
        sm = SemanticMemory()
        scan = ScanResult(
            hostname="test-host", os_name="Linux", os_version="6.0",
            os_arch="x86_64", cpu_info="Test CPU", cpu_cores=4,
            memory_total_gb=16.0, memory_available_gb=8.0,
            ip_addresses=["10.0.0.1"],
        )

        result = await store_scan_in_memory(scan, em, sm)

        assert result["notes"] == 1
        assert result["entities"] >= 2  # host + IP

        # Verify note is pinned
        notes = await em.get_all_notes()
        assert len(notes) == 1
        assert notes[0].pinned is True
        assert "test-host" in notes[0].content

    @pytest.mark.asyncio
    async def test_creates_kg_entities(self):
        em = EpisodicMemory()
        sm = SemanticMemory()
        scan = ScanResult(
            hostname="srv1", os_name="Linux", os_version="6.0",
            os_arch="x86_64",
            docker_version="24.0",
            ip_addresses=["10.0.0.1", "10.0.0.2"],
        )

        await store_scan_in_memory(scan, em, sm)

        # Host entity
        host = await sm.get_entity("host:srv1")
        assert host is not None
        assert host.name == "srv1"

        # IP entities
        ip1 = await sm.get_entity("ip:10.0.0.1")
        assert ip1 is not None

        # Docker entity
        docker = await sm.get_entity("tool:docker")
        assert docker is not None

        # Relations
        rels = await sm.get_relations("host:srv1")
        assert len(rels) >= 3  # 2 IPs + docker
