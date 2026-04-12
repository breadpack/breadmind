"""Device node foundation: peripheral devices exposing capabilities to the agent."""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class DeviceCapability:
    name: str  # "camera", "location", "screen", "voice", "sms", "contacts"
    available: bool = True
    requires_foreground: bool = False

@dataclass
class DeviceNode:
    id: str
    name: str
    platform: str  # "macos", "ios", "android", "linux", "windows"
    capabilities: list[DeviceCapability] = field(default_factory=list)
    connected: bool = False
    last_seen: float = field(default_factory=time.time)

class DeviceNodeRegistry:
    """Registry of connected device nodes."""

    def __init__(self) -> None:
        self._nodes: dict[str, DeviceNode] = {}

    def register(self, node: DeviceNode) -> None:
        node.connected = True
        node.last_seen = time.time()
        self._nodes[node.id] = node
        logger.info("Device node registered: %s (%s)", node.name, node.platform)

    def unregister(self, node_id: str) -> bool:
        node = self._nodes.pop(node_id, None)
        if node:
            node.connected = False
            return True
        return False

    def heartbeat(self, node_id: str) -> bool:
        node = self._nodes.get(node_id)
        if node:
            node.last_seen = time.time()
            return True
        return False

    def get_node(self, node_id: str) -> DeviceNode | None:
        return self._nodes.get(node_id)

    def find_by_capability(self, capability: str) -> list[DeviceNode]:
        return [n for n in self._nodes.values()
                if n.connected and any(c.name == capability and c.available
                                       for c in n.capabilities)]

    def list_nodes(self, connected_only: bool = True) -> list[DeviceNode]:
        nodes = list(self._nodes.values())
        if connected_only:
            nodes = [n for n in nodes if n.connected]
        return nodes

    def cleanup_stale(self, timeout_seconds: float = 300) -> int:
        """Remove nodes not seen within timeout."""
        now = time.time()
        stale = [nid for nid, n in self._nodes.items()
                 if now - n.last_seen > timeout_seconds]
        for nid in stale:
            self._nodes[nid].connected = False
        return len(stale)
