"""DAG data structure with topological ordering and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DAGValidationError(ValueError):
    pass


@dataclass
class Step:
    id: str
    title: str
    tool: str | None
    args: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    max_attempts: int = 3


@dataclass
class DAG:
    steps: list[Step]

    def _by_id(self) -> dict[str, Step]:
        return {s.id: s for s in self.steps}

    def validate(self) -> None:
        seen: set[str] = set()
        for s in self.steps:
            if s.id in seen:
                raise DAGValidationError(f"duplicate step id: {s.id}")
            seen.add(s.id)
        for s in self.steps:
            for dep in s.depends_on:
                if dep not in seen:
                    raise DAGValidationError(f"step '{s.id}' depends on missing '{dep}'")
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {s.id: WHITE for s in self.steps}
        by_id = self._by_id()

        def visit(node: str) -> None:
            color[node] = GRAY
            for dep in by_id[node].depends_on:
                if color[dep] == GRAY:
                    raise DAGValidationError(f"cycle detected at step '{dep}'")
                if color[dep] == WHITE:
                    visit(dep)
            color[node] = BLACK

        for s in self.steps:
            if color[s.id] == WHITE:
                visit(s.id)

    def topological_order(self) -> list[str]:
        self.validate()
        order: list[str] = []
        visited: set[str] = set()
        by_id = self._by_id()

        def visit(node: str) -> None:
            if node in visited:
                return
            for dep in by_id[node].depends_on:
                visit(dep)
            visited.add(node)
            order.append(node)

        for s in self.steps:
            visit(s.id)
        return order

    def ready_steps(self, completed: set[str]) -> list[str]:
        ready: list[str] = []
        for s in self.steps:
            if s.id in completed:
                continue
            if not s.depends_on:
                # Root steps are only "ready" before any progress has been made.
                if not completed:
                    ready.append(s.id)
                continue
            if all(dep in completed for dep in s.depends_on):
                ready.append(s.id)
        return ready

    def to_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "title": s.title,
                "tool": s.tool,
                "args": s.args,
                "depends_on": s.depends_on,
                "timeout_seconds": s.timeout_seconds,
                "max_attempts": s.max_attempts,
            }
            for s in self.steps
        ]

    @classmethod
    def from_payload(cls, data: list[dict[str, Any]]) -> "DAG":
        steps = [
            Step(
                id=d["id"],
                title=d["title"],
                tool=d.get("tool"),
                args=d.get("args", {}),
                depends_on=list(d.get("depends_on", [])),
                timeout_seconds=int(d.get("timeout_seconds", 300)),
                max_attempts=int(d.get("max_attempts", 3)),
            )
            for d in data
        ]
        dag = cls(steps=steps)
        dag.validate()
        return dag
