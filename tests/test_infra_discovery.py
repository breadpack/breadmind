# tests/test_infra_discovery.py
"""Infrastructure discovery tests."""
import pytest


@pytest.mark.asyncio
async def test_check_port_closed():
    from breadmind.core.infra_discovery import check_port
    # Port 1 is almost certainly closed on localhost
    is_open, _ = await check_port("127.0.0.1", 1, timeout=0.5)
    assert is_open is False


def test_detect_network():
    from breadmind.core.infra_discovery import _detect_network
    network = _detect_network()
    assert "/" in network  # Should be CIDR format
    assert "." in network  # Should be IPv4


def test_generate_ips():
    from breadmind.core.infra_discovery import _generate_ips
    ips = _generate_ips("192.168.1.0/24", count=5)
    assert len(ips) > 0
    assert "192.168.1.1" in ips  # Gateway always included
    assert all(ip.startswith("192.168.1.") for ip in ips)


def test_extract_title():
    from breadmind.core.infra_discovery import _extract_title
    assert _extract_title("<html><title>Proxmox VE</title></html>") == "Proxmox VE"
    assert _extract_title("<html><body>no title</body></html>") == ""


def test_service_signatures():
    from breadmind.core.infra_discovery import SERVICE_SIGNATURES
    assert 8006 in SERVICE_SIGNATURES  # Proxmox
    assert 6443 in SERVICE_SIGNATURES  # K8s
    assert 5001 in SERVICE_SIGNATURES  # Synology


def test_infra_routes_import():
    from breadmind.web.routes.infrastructure import router
    assert router.prefix == "/api/infra"
