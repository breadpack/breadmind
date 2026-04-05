"""Dependency graph for tools, skills, MCP servers, and plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeType(str, Enum):
    TOOL = "tool"
    SKILL = "skill"
    MCP_SERVER = "mcp_server"
    PLUGIN = "plugin"


@dataclass
class DependencyNode:
    name: str
    type: NodeType
    depends_on: list[str] = field(default_factory=list)
    depended_by: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class DependencyCheck:
    can_remove: bool
    blocked_by: list[str] = field(default_factory=list)
    message: str = ""


class CyclicDependencyError(Exception):
    """Raised when adding a dependency would create a cycle."""


class DependencyGraph:
    """Tracks dependencies between all managed components.

    Features:
    - Declare dependencies between tools, skills, MCP servers, plugins
    - Prevent removal of depended-upon components
    - Auto-install dependencies during installation
    - Detect circular dependencies
    - Topological sort for install/load ordering
    """

    def __init__(self) -> None:
        self._nodes: dict[str, DependencyNode] = {}

    # -- Node management --

    def add_node(
        self,
        name: str,
        node_type: NodeType,
        depends_on: list[str] | None = None,
    ) -> DependencyNode:
        """Add a component to the graph with its dependencies."""
        if name in self._nodes:
            raise ValueError(f"Node '{name}' already exists")

        node = DependencyNode(
            name=name,
            type=node_type,
            depends_on=list(depends_on) if depends_on else [],
        )
        self._nodes[name] = node

        # Register reverse edges for existing dependency targets.
        for dep in node.depends_on:
            if dep in self._nodes:
                if name not in self._nodes[dep].depended_by:
                    self._nodes[dep].depended_by.append(name)

        return node

    def remove_node(self, name: str) -> bool:
        """Remove a node. Returns False if other nodes depend on it."""
        check = self.check_removal(name)
        if not check.can_remove:
            return False

        node = self._nodes.pop(name)

        # Clean up reverse edges from dependencies.
        for dep_name in node.depends_on:
            dep_node = self._nodes.get(dep_name)
            if dep_node and name in dep_node.depended_by:
                dep_node.depended_by.remove(name)

        return True

    def add_dependency(self, name: str, depends_on: str) -> None:
        """Add a dependency edge between two existing nodes."""
        if name not in self._nodes:
            raise KeyError(f"Node '{name}' not found")
        if depends_on not in self._nodes:
            raise KeyError(f"Node '{depends_on}' not found")

        node = self._nodes[name]
        target = self._nodes[depends_on]

        if depends_on in node.depends_on:
            return  # Already exists.

        # Check if adding this edge would create a cycle.
        if name in self.get_all_dependencies(depends_on):
            raise CyclicDependencyError(
                f"Adding dependency {name} -> {depends_on} would create a cycle"
            )

        node.depends_on.append(depends_on)
        if name not in target.depended_by:
            target.depended_by.append(name)

    def get_node(self, name: str) -> DependencyNode | None:
        return self._nodes.get(name)

    @property
    def nodes(self) -> dict[str, DependencyNode]:
        return dict(self._nodes)

    # -- Query helpers --

    def get_dependencies(self, name: str) -> list[str]:
        """Get direct dependencies of a node."""
        node = self._nodes.get(name)
        if node is None:
            return []
        return list(node.depends_on)

    def get_all_dependencies(self, name: str) -> list[str]:
        """Get transitive (recursive) dependencies via BFS."""
        visited: set[str] = set()
        queue = list(self.get_dependencies(name))

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self.get_dependencies(current))

        return sorted(visited)

    def get_dependents(self, name: str) -> list[str]:
        """Get nodes that directly depend on this node."""
        node = self._nodes.get(name)
        if node is None:
            return []
        return list(node.depended_by)

    # -- Removal safety --

    def check_removal(self, name: str) -> DependencyCheck:
        """Check if a node can be safely removed."""
        node = self._nodes.get(name)
        if node is None:
            return DependencyCheck(
                can_remove=False, message=f"Node '{name}' not found"
            )

        if node.depended_by:
            return DependencyCheck(
                can_remove=False,
                blocked_by=list(node.depended_by),
                message=(
                    f"Cannot remove '{name}': "
                    f"depended on by {', '.join(node.depended_by)}"
                ),
            )

        return DependencyCheck(can_remove=True, message=f"'{name}' can be removed")

    # -- Ordering --

    def install_order(self, names: list[str]) -> list[str]:
        """Return topological sort for a subset of nodes (Kahn's algorithm)."""
        # Build sub-graph limited to requested names.
        subset = set(names)
        in_degree: dict[str, int] = {n: 0 for n in names}

        for n in names:
            node = self._nodes.get(n)
            if node is None:
                continue
            for dep in node.depends_on:
                if dep in subset:
                    in_degree[n] += 1

        queue = sorted(n for n, d in in_degree.items() if d == 0)
        result: list[str] = []

        while queue:
            current = queue.pop(0)
            result.append(current)
            node = self._nodes.get(current)
            if node is None:
                continue
            for dependent_name in node.depended_by:
                if dependent_name in in_degree:
                    in_degree[dependent_name] -= 1
                    if in_degree[dependent_name] == 0:
                        queue.append(dependent_name)
            queue.sort()

        return result

    def get_install_plan(self, name: str) -> list[str]:
        """Ordered list of components to install (deps first, then target)."""
        all_deps = self.get_all_dependencies(name)
        all_names = all_deps + [name]
        return self.install_order(all_names)

    def get_removal_plan(self, name: str) -> list[str]:
        """Ordered list to remove (dependents first, then target)."""
        result: list[str] = []
        visited: set[str] = set()

        def _collect(n: str) -> None:
            if n in visited:
                return
            visited.add(n)
            node = self._nodes.get(n)
            if node is None:
                return
            for dep_by in node.depended_by:
                _collect(dep_by)
            result.append(n)

        _collect(name)
        return result

    # -- Cycle detection --

    def detect_cycles(self) -> list[list[str]]:
        """Detect circular dependencies using DFS. Returns list of cycles."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in self._nodes}
        parent: dict[str, str | None] = {n: None for n in self._nodes}
        cycles: list[list[str]] = []

        def _dfs(u: str) -> None:
            color[u] = GRAY
            node = self._nodes[u]
            for v in node.depends_on:
                if v not in self._nodes:
                    continue
                if color[v] == GRAY:
                    # Back edge found -- reconstruct cycle.
                    cycle = [v, u]
                    cur = u
                    while cur != v:
                        cur = parent.get(cur)  # type: ignore[assignment]
                        if cur is None or cur == v:
                            break
                        cycle.append(cur)
                    cycle.reverse()
                    cycles.append(cycle)
                elif color[v] == WHITE:
                    parent[v] = u
                    _dfs(v)
            color[u] = BLACK

        for n in self._nodes:
            if color[n] == WHITE:
                _dfs(n)

        return cycles

    # -- Visualization --

    def visualize(self) -> str:
        """Return a text-based visualization of the dependency graph."""
        if not self._nodes:
            return "(empty graph)"

        lines: list[str] = []
        for name in sorted(self._nodes):
            node = self._nodes[name]
            deps = ", ".join(node.depends_on) if node.depends_on else "(none)"
            by = ", ".join(node.depended_by) if node.depended_by else "(none)"
            lines.append(
                f"[{node.type.value}] {name}\n"
                f"  depends on : {deps}\n"
                f"  required by: {by}"
            )
        return "\n".join(lines)
