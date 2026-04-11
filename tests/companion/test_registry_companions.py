"""Tests for AgentRegistry companion/worker filtering."""

from __future__ import annotations

from breadmind.network.registry import AgentRegistry


def test_list_companions():
    reg = AgentRegistry()
    reg.register("comp-1", "host-a", environment={"agent_type": "companion", "device_name": "laptop"})
    reg.register("worker-1", "host-b", environment={"agent_type": "worker"})
    reg.register("comp-2", "host-c", environment={"agent_type": "companion", "device_name": "phone"})

    companions = reg.list_companions()
    assert len(companions) == 2
    ids = {a.agent_id for a in companions}
    assert ids == {"comp-1", "comp-2"}


def test_list_workers_excludes_companions():
    reg = AgentRegistry()
    reg.register("comp-1", "host-a", environment={"agent_type": "companion"})
    reg.register("worker-1", "host-b", environment={"agent_type": "worker"})
    reg.register("worker-2", "host-c", environment={})  # no agent_type

    workers = reg.list_workers()
    assert len(workers) == 2
    ids = {a.agent_id for a in workers}
    assert ids == {"worker-1", "worker-2"}


def test_empty_registry():
    reg = AgentRegistry()
    assert reg.list_companions() == []
    assert reg.list_workers() == []
