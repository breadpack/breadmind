"""Tests for device node foundation."""
from __future__ import annotations
import time

from breadmind.core.device_node import (
    DeviceCapability,
    DeviceNode,
    DeviceNodeRegistry,
)


def test_register_node():
    registry = DeviceNodeRegistry()
    node = DeviceNode(id="phone1", name="My Phone", platform="android")
    registry.register(node)
    assert node.connected is True
    assert registry.get_node("phone1") is node
    assert len(registry.list_nodes()) == 1


def test_find_by_capability():
    registry = DeviceNodeRegistry()
    node = DeviceNode(
        id="phone1", name="My Phone", platform="android",
        capabilities=[
            DeviceCapability(name="camera", available=True),
            DeviceCapability(name="location", available=False),
        ],
    )
    registry.register(node)
    assert len(registry.find_by_capability("camera")) == 1
    assert len(registry.find_by_capability("location")) == 0  # not available
    assert len(registry.find_by_capability("sms")) == 0


def test_heartbeat():
    registry = DeviceNodeRegistry()
    node = DeviceNode(id="phone1", name="My Phone", platform="android")
    registry.register(node)
    old_time = node.last_seen
    # Heartbeat updates last_seen
    assert registry.heartbeat("phone1") is True
    assert node.last_seen >= old_time
    assert registry.heartbeat("nonexistent") is False


def test_cleanup_stale():
    registry = DeviceNodeRegistry()
    node = DeviceNode(id="phone1", name="My Phone", platform="android")
    registry.register(node)
    # Make it stale by backdating last_seen
    node.last_seen = time.time() - 600
    count = registry.cleanup_stale(timeout_seconds=300)
    assert count == 1
    assert node.connected is False


def test_unregister():
    registry = DeviceNodeRegistry()
    node = DeviceNode(id="phone1", name="My Phone", platform="android")
    registry.register(node)
    assert registry.unregister("phone1") is True
    assert node.connected is False
    assert registry.unregister("phone1") is False
