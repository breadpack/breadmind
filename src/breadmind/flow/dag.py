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
class DAGMutation:
    added: list[dict] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)


@dataclass
class DAG:
    steps: list[Step]

    def apply_mutation(self, mutation: "DAGMutation") -> "DAG":
        """Return a new DAG with the mutation applied.

        Raises DAGValidationError if the result is invalid (cycle, missing
        dependency, duplicate id, or reference to a non-existent step to
        modify).
        """
        new_steps = list(self.steps)

        # Remove
        removed_set = set(mutation.removed)
        new_steps = [s for s in new_steps if s.id not in removed_set]

        # Modify (replace by id)
        by_id = {s.id: i for i, s in enumerate(new_steps)}
        for mod in mutation.modified:
            sid = mod["id"]
            if sid not in by_id:
                raise DAGValidationError(f"cannot modify missing step '{sid}'")
            new_steps[by_id[sid]] = Step(
                id=mod["id"],
                title=mod["title"],
                tool=mod.get("tool"),
                args=dict(mod.get("args", {})),
                depends_on=list(mod.get("depends_on", [])),
                timeout_seconds=int(mod.get("timeout_seconds", 300)),
                max_attempts=int(mod.get("max_attempts", 3)),
            )

        # Add
        for add in mutation.added:
            new_steps.append(Step(
                id=add["id"],
                title=add["title"],
                tool=add.get("tool"),
                args=dict(add.get("args", {})),
                depends_on=list(add.get("depends_on", [])),
                timeout_seconds=int(add.get("timeout_seconds", 300)),
                max_attempts=int(add.get("max_attempts", 3)),
            ))

        new_dag = DAG(steps=new_steps)
        new_dag.validate()
        return new_dag

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
