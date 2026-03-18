"""Router manager tests."""
import pytest


def test_get_capabilities_openwrt():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    cap = mgr.get_capabilities("openwrt")
    assert cap.ssh is True
    assert "uci" in cap.cli_commands[0]


def test_get_capabilities_iptime():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    cap = mgr.get_capabilities("iptime")
    assert cap.ssh is False
    assert cap.web_api is True


def test_get_capabilities_unknown():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    cap = mgr.get_capabilities("unknown_brand")
    assert "알 수 없는" in cap.description


def test_is_connected_false():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    assert mgr.is_connected("192.168.0.1") is False


def test_disconnect_not_connected():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    assert mgr.disconnect("192.168.0.1") is False


def test_all_router_types_have_description():
    from breadmind.core.router_manager import ROUTER_CAPABILITIES

    for rtype, cap in ROUTER_CAPABILITIES.items():
        assert cap.description, f"{rtype} has no description"
        assert cap.setup_guide, f"{rtype} has no setup guide"


def test_singleton_returns_same_instance():
    from breadmind.core.router_manager import get_router_manager

    mgr1 = get_router_manager()
    mgr2 = get_router_manager()
    assert mgr1 is mgr2


def test_capabilities_case_insensitive():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    cap = mgr.get_capabilities("OpenWrt")
    assert cap.ssh is True


@pytest.mark.asyncio
async def test_connect_no_ssh_router():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    result = await mgr.connect("192.168.0.1", "iptime", "admin")
    assert result["success"] is True
    assert result.get("mode") == "browser"


@pytest.mark.asyncio
async def test_execute_not_connected():
    from breadmind.core.router_manager import RouterManager

    mgr = RouterManager()
    result = await mgr.execute("192.168.0.1", "uptime")
    assert "[error]" in result
