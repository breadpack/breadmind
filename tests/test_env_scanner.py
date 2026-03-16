"""Tests for environment scanner."""
import pytest
from breadmind.core.env_scanner import (
    scan_environment, store_scan_in_memory, ScanResult,
    detect_new_tool, detect_removed_tool, reconcile_tools,
    _extract_tool_from_install_cmd, _extract_tool_from_uninstall_cmd,
)
from breadmind.memory.episodic import EpisodicMemory
from breadmind.memory.semantic import SemanticMemory
from breadmind.storage.models import KGEntity


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

        # Relations — at least the 2 IP addresses
        rels = await sm.get_relations("host:srv1")
        assert len(rels) >= 2  # 2 IPs (tool relations only added on initial scan)


class TestRescan:
    @pytest.mark.asyncio
    async def test_rescan_updates_existing_note(self):
        em = EpisodicMemory()
        sm = SemanticMemory()

        # Initial scan
        scan1 = ScanResult(
            hostname="srv1", os_name="Linux", os_version="6.0", os_arch="x86_64",
            memory_total_gb=32.0, memory_available_gb=16.0,
            disks=[{"drive": "/", "total_gb": 500, "free_gb": 200, "percent_used": 60}],
        )
        await store_scan_in_memory(scan1, em, sm)
        assert len(em._notes) == 1
        assert "16.0GB available" in em._notes[0].content

        # Rescan with changed values
        scan2 = ScanResult(
            hostname="srv1", os_name="Linux", os_version="6.0", os_arch="x86_64",
            memory_total_gb=32.0, memory_available_gb=8.0,  # Memory changed
            disks=[{"drive": "/", "total_gb": 500, "free_gb": 100, "percent_used": 80}],
        )
        result = await store_scan_in_memory(scan2, em, sm)

        # Should update, not duplicate
        assert len(em._notes) == 1
        assert result["updated"] is True
        assert "8.0GB available" in em._notes[0].content

    @pytest.mark.asyncio
    async def test_rescan_updates_kg_entities(self):
        em = EpisodicMemory()
        sm = SemanticMemory()

        # Initial scan with IP 10.0.0.1
        scan1 = ScanResult(
            hostname="srv1", os_name="Linux", os_version="6.0", os_arch="x86_64",
            ip_addresses=["10.0.0.1"],
        )
        await store_scan_in_memory(scan1, em, sm)
        assert await sm.get_entity("ip:10.0.0.1") is not None

        # Rescan — IP changed to 10.0.0.2
        scan2 = ScanResult(
            hostname="srv1", os_name="Linux", os_version="6.0", os_arch="x86_64",
            ip_addresses=["10.0.0.2"],
        )
        await store_scan_in_memory(scan2, em, sm)

        # Old IP removed, new IP exists
        assert await sm.get_entity("ip:10.0.0.1") is None
        assert await sm.get_entity("ip:10.0.0.2") is not None

    @pytest.mark.asyncio
    async def test_rescan_updates_disk_usage(self):
        em = EpisodicMemory()
        sm = SemanticMemory()

        scan1 = ScanResult(
            hostname="srv1", os_name="Linux", os_version="6.0", os_arch="x86_64",
            disks=[{"drive": "C:", "total_gb": 500, "free_gb": 300, "percent_used": 40}],
        )
        await store_scan_in_memory(scan1, em, sm)

        disk = await sm.get_entity("disk:srv1:C:")
        assert disk.properties["free_gb"] == 300.0

        # Rescan — disk usage changed
        scan2 = ScanResult(
            hostname="srv1", os_name="Linux", os_version="6.0", os_arch="x86_64",
            disks=[{"drive": "C:", "total_gb": 500, "free_gb": 100, "percent_used": 80}],
        )
        await store_scan_in_memory(scan2, em, sm)

        disk = await sm.get_entity("disk:srv1:C:")
        assert disk.properties["free_gb"] == 100.0
        assert disk.properties["percent_used"] == 80.0


class TestToolDetection:
    def test_extract_tool_from_pip_install(self):
        assert _extract_tool_from_install_cmd("pip install flask") == "flask"
        assert _extract_tool_from_install_cmd("pip3 install -U requests") == "requests"

    def test_extract_tool_from_apt_install(self):
        assert _extract_tool_from_install_cmd("apt install -y nginx") == "nginx"
        assert _extract_tool_from_install_cmd("apt-get install curl") == "curl"

    def test_extract_tool_from_choco(self):
        assert _extract_tool_from_install_cmd("choco install terraform") == "terraform"

    def test_extract_tool_from_npm(self):
        assert _extract_tool_from_install_cmd("npm install -g typescript") == "typescript"

    def test_extract_tool_from_unknown(self):
        assert _extract_tool_from_install_cmd("ls -la") is None

    @pytest.mark.asyncio
    async def test_detect_new_tool_ignores_non_install(self):
        sm = SemanticMemory()
        result = await detect_new_tool("ls -la", "file1 file2", sm)
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_new_tool_with_known_tool(self):
        sm = SemanticMemory()
        # Pre-register python as known
        await sm.add_entity(KGEntity(id="tool:python", entity_type="infra_component", name="python"))

        result = await detect_new_tool(
            "pip install python",
            "Successfully installed python",
            sm,
        )
        assert result is None  # Already known


class TestToolRemovalDetection:
    def test_extract_tool_from_pip_uninstall(self):
        assert _extract_tool_from_uninstall_cmd("pip uninstall flask") == "flask"
        assert _extract_tool_from_uninstall_cmd("pip3 uninstall -y requests") == "requests"

    def test_extract_tool_from_apt_remove(self):
        assert _extract_tool_from_uninstall_cmd("apt remove nginx") == "nginx"
        assert _extract_tool_from_uninstall_cmd("apt-get purge curl") == "curl"
        assert _extract_tool_from_uninstall_cmd("apt purge curl") == "curl"

    def test_extract_tool_from_choco_uninstall(self):
        assert _extract_tool_from_uninstall_cmd("choco uninstall terraform") == "terraform"

    def test_extract_tool_from_unknown(self):
        assert _extract_tool_from_uninstall_cmd("ls -la") is None

    @pytest.mark.asyncio
    async def test_detect_removed_ignores_non_uninstall(self):
        sm = SemanticMemory()
        result = await detect_removed_tool("ls -la", "file1 file2", sm)
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_removed_unknown_tool(self):
        sm = SemanticMemory()
        # Tool not in KG — nothing to remove
        result = await detect_removed_tool(
            "pip uninstall nonexistenttool",
            "Successfully uninstalled nonexistenttool",
            sm,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_reconcile_removes_missing_tools(self):
        sm = SemanticMemory()
        # Add a tool that doesn't actually exist
        await sm.add_entity(KGEntity(
            id="tool:fake_nonexistent_tool_xyz",
            entity_type="infra_component",
            name="fake_nonexistent_tool_xyz",
        ))
        # Add a tool that does exist (python)
        await sm.add_entity(KGEntity(
            id="tool:python",
            entity_type="infra_component",
            name="python",
        ))

        removed = await reconcile_tools(sm)

        assert "fake_nonexistent_tool_xyz" in removed
        assert "python" not in removed
        assert "tool:fake_nonexistent_tool_xyz" not in sm._entities
        assert "tool:python" in sm._entities
