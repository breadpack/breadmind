"""Tests for browser network monitoring via CDP."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_cdp():
    cdp = AsyncMock()
    cdp.send = AsyncMock(return_value={})
    cdp.on = MagicMock()
    return cdp


async def test_request_entry_creation():
    from breadmind.tools.browser_network import RequestEntry
    entry = RequestEntry(
        url="https://api.example.com/data", method="GET", status=200,
        request_headers={"Accept": "application/json"},
        response_headers={"Content-Type": "application/json"},
        body_size=1024, duration_ms=150.0, resource_type="xhr", timestamp=1000.0,
    )
    assert entry.url == "https://api.example.com/data"
    assert entry.status == 200
    d = entry.to_dict()
    assert d["method"] == "GET"


async def test_network_monitor_start_capture(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    await monitor.start_capture()
    assert monitor._capturing is True
    mock_cdp.send.assert_any_call("Network.enable", {})


async def test_network_monitor_stop_capture(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    monitor._capturing = True
    entries = await monitor.stop_capture()
    assert monitor._capturing is False
    assert isinstance(entries, list)


async def test_network_monitor_on_request(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    monitor._capturing = True
    monitor._on_request_will_be_sent({
        "requestId": "r1",
        "request": {"url": "https://example.com/api", "method": "POST", "headers": {"Content-Type": "application/json"}},
        "type": "XHR", "timestamp": 1000.0,
    })
    assert "r1" in monitor._pending


async def test_network_monitor_on_response(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    monitor._capturing = True
    monitor._pending["r1"] = {
        "url": "https://example.com/api", "method": "POST",
        "request_headers": {}, "resource_type": "xhr", "timestamp": 1000.0,
    }
    monitor._on_response_received({
        "requestId": "r1",
        "response": {"status": 200, "headers": {"Content-Type": "application/json"}, "encodedDataLength": 512},
        "timestamp": 1000.15,
    })
    assert len(monitor._entries) == 1
    assert monitor._entries[0].status == 200
    assert monitor._entries[0].duration_ms == pytest.approx(150.0, abs=1.0)


async def test_network_monitor_max_entries(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp, max_entries=3)
    monitor._capturing = True
    for i in range(5):
        monitor._pending[f"r{i}"] = {
            "url": f"https://example.com/{i}", "method": "GET",
            "request_headers": {}, "resource_type": "document", "timestamp": 1000.0 + i,
        }
        monitor._on_response_received({
            "requestId": f"r{i}",
            "response": {"status": 200, "headers": {}, "encodedDataLength": 100},
            "timestamp": 1000.1 + i,
        })
    assert len(monitor._entries) == 3
    assert monitor._entries[0].url == "https://example.com/2"


async def test_block_urls(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor
    monitor = NetworkMonitor(mock_cdp)
    await monitor.block_urls(["*analytics*", "*ads*"])
    mock_cdp.send.assert_any_call("Network.setBlockedURLs", {"urls": ["*analytics*", "*ads*"]})


async def test_export_har(mock_cdp):
    from breadmind.tools.browser_network import NetworkMonitor, RequestEntry
    monitor = NetworkMonitor(mock_cdp)
    monitor._entries = [
        RequestEntry(url="https://example.com", method="GET", status=200,
                     request_headers={}, response_headers={}, body_size=1024,
                     duration_ms=100.0, resource_type="document", timestamp=1000.0)
    ]
    har = monitor.export_har()
    assert "log" in har
    assert len(har["log"]["entries"]) == 1
