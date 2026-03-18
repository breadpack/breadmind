"""Network awareness tests."""
import pytest


def test_get_local_ip():
    from breadmind.core.network_awareness import _get_local_ip
    ip = _get_local_ip()
    assert "." in ip
    assert ip != ""


def test_ip_to_subnet():
    from breadmind.core.network_awareness import _ip_to_subnet
    assert _ip_to_subnet("192.168.0.15") == "192.168.0.0"
    assert _ip_to_subnet("10.0.1.50") == "10.0.1.0"


def test_extract_iptime_model():
    from breadmind.core.network_awareness import _extract_iptime_model
    assert _extract_iptime_model("ipTIME A8004T firmware") == "A8004"
    assert _extract_iptime_model("no model info") == "unknown"


def test_guess_device_type():
    from breadmind.core.network_awareness import _guess_device_type, NetworkDevice
    dev = NetworkDevice(ip="192.168.0.100", hostname="DiskStation")
    assert _guess_device_type(dev) == "nas"

    dev2 = NetworkDevice(ip="192.168.0.50", hostname="proxmox-node1")
    assert _guess_device_type(dev2) == "server"

    dev3 = NetworkDevice(ip="192.168.0.200", hostname="iPhone-13")
    assert _guess_device_type(dev3) == "phone"


@pytest.mark.asyncio
async def test_detect_environment_structure():
    from breadmind.core.network_awareness import detect_environment
    env = await detect_environment()
    assert env.local_ip != ""
    assert env.gateway_ip != ""
    assert isinstance(env.devices, list)
