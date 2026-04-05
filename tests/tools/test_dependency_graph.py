"""Tests for dependency_graph module."""

from __future__ import annotations

import pytest

from breadmind.tools.dependency_graph import (
    CyclicDependencyError,
    DependencyGraph,
    NodeType,
)


@pytest.fixture
def graph() -> DependencyGraph:
    return DependencyGraph()


# -- add_node / get_node --


def test_add_and_get_node(graph: DependencyGraph):
    node = graph.add_node("tool_a", NodeType.TOOL)
    assert node.name == "tool_a"
    assert node.type == NodeType.TOOL
    assert graph.get_node("tool_a") is node


def test_add_duplicate_node_raises(graph: DependencyGraph):
    graph.add_node("tool_a", NodeType.TOOL)
    with pytest.raises(ValueError, match="already exists"):
        graph.add_node("tool_a", NodeType.TOOL)


def test_add_node_with_dependencies(graph: DependencyGraph):
    graph.add_node("base", NodeType.PLUGIN)
    node = graph.add_node("child", NodeType.TOOL, depends_on=["base"])
    assert "base" in node.depends_on
    assert "child" in graph.get_node("base").depended_by


def test_get_node_missing(graph: DependencyGraph):
    assert graph.get_node("nonexistent") is None


# -- remove_node --


def test_remove_leaf_node(graph: DependencyGraph):
    graph.add_node("leaf", NodeType.TOOL)
    assert graph.remove_node("leaf") is True
    assert graph.get_node("leaf") is None


def test_remove_depended_node_fails(graph: DependencyGraph):
    graph.add_node("base", NodeType.PLUGIN)
    graph.add_node("child", NodeType.TOOL, depends_on=["base"])
    assert graph.remove_node("base") is False
    assert graph.get_node("base") is not None


def test_remove_cleans_reverse_edges(graph: DependencyGraph):
    graph.add_node("base", NodeType.PLUGIN)
    graph.add_node("child", NodeType.TOOL, depends_on=["base"])
    # Remove child (the dependent) -- should clean up base.depended_by.
    assert graph.remove_node("child") is True
    assert graph.get_node("base").depended_by == []


# -- add_dependency --


def test_add_dependency_between_existing_nodes(graph: DependencyGraph):
    graph.add_node("a", NodeType.TOOL)
    graph.add_node("b", NodeType.TOOL)
    graph.add_dependency("a", "b")
    assert "b" in graph.get_dependencies("a")
    assert "a" in graph.get_dependents("b")


def test_add_dependency_missing_node_raises(graph: DependencyGraph):
    graph.add_node("a", NodeType.TOOL)
    with pytest.raises(KeyError):
        graph.add_dependency("a", "missing")


def test_add_dependency_cycle_raises(graph: DependencyGraph):
    graph.add_node("a", NodeType.TOOL)
    graph.add_node("b", NodeType.TOOL)
    graph.add_dependency("a", "b")
    with pytest.raises(CyclicDependencyError):
        graph.add_dependency("b", "a")


# -- get_all_dependencies --


def test_get_all_dependencies_transitive(graph: DependencyGraph):
    graph.add_node("c", NodeType.TOOL)
    graph.add_node("b", NodeType.TOOL, depends_on=["c"])
    graph.add_node("a", NodeType.TOOL, depends_on=["b"])
    all_deps = graph.get_all_dependencies("a")
    assert "b" in all_deps
    assert "c" in all_deps


# -- check_removal --


def test_check_removal_safe(graph: DependencyGraph):
    graph.add_node("x", NodeType.SKILL)
    check = graph.check_removal("x")
    assert check.can_remove is True


def test_check_removal_blocked(graph: DependencyGraph):
    graph.add_node("x", NodeType.SKILL)
    graph.add_node("y", NodeType.TOOL, depends_on=["x"])
    check = graph.check_removal("x")
    assert check.can_remove is False
    assert "y" in check.blocked_by


def test_check_removal_missing_node(graph: DependencyGraph):
    check = graph.check_removal("ghost")
    assert check.can_remove is False


# -- install_order --


def test_install_order_topological(graph: DependencyGraph):
    graph.add_node("c", NodeType.TOOL)
    graph.add_node("b", NodeType.TOOL, depends_on=["c"])
    graph.add_node("a", NodeType.TOOL, depends_on=["b"])
    order = graph.install_order(["a", "b", "c"])
    assert order.index("c") < order.index("b")
    assert order.index("b") < order.index("a")


# -- get_install_plan / get_removal_plan --


def test_install_plan(graph: DependencyGraph):
    graph.add_node("base", NodeType.PLUGIN)
    graph.add_node("mid", NodeType.SKILL, depends_on=["base"])
    graph.add_node("top", NodeType.TOOL, depends_on=["mid"])
    plan = graph.get_install_plan("top")
    assert plan[-1] == "top"
    assert plan.index("base") < plan.index("mid")


def test_removal_plan(graph: DependencyGraph):
    graph.add_node("base", NodeType.PLUGIN)
    graph.add_node("child", NodeType.TOOL, depends_on=["base"])
    plan = graph.get_removal_plan("base")
    assert plan[0] == "child"
    assert plan[-1] == "base"


# -- detect_cycles --


def test_detect_cycles_none(graph: DependencyGraph):
    graph.add_node("a", NodeType.TOOL)
    graph.add_node("b", NodeType.TOOL, depends_on=["a"])
    assert graph.detect_cycles() == []


def test_detect_cycles_with_forced_cycle(graph: DependencyGraph):
    # Manually inject a cycle to test detection.
    graph.add_node("a", NodeType.TOOL)
    graph.add_node("b", NodeType.TOOL, depends_on=["a"])
    # Force a back edge bypassing the safety check.
    graph._nodes["a"].depends_on.append("b")
    cycles = graph.detect_cycles()
    assert len(cycles) >= 1


# -- visualize --


def test_visualize_empty(graph: DependencyGraph):
    assert graph.visualize() == "(empty graph)"


def test_visualize_with_nodes(graph: DependencyGraph):
    graph.add_node("alpha", NodeType.TOOL)
    graph.add_node("beta", NodeType.SKILL, depends_on=["alpha"])
    text = graph.visualize()
    assert "alpha" in text
    assert "beta" in text
    assert "[tool]" in text
    assert "[skill]" in text
