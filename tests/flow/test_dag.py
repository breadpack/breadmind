import pytest

from breadmind.flow.dag import DAG, Step, DAGValidationError


def test_topo_sort_linear():
    dag = DAG(steps=[
        Step(id="s1", title="First", tool="t", args={}, depends_on=[]),
        Step(id="s2", title="Second", tool="t", args={}, depends_on=["s1"]),
        Step(id="s3", title="Third", tool="t", args={}, depends_on=["s2"]),
    ])
    order = dag.topological_order()
    assert order == ["s1", "s2", "s3"]


def test_ready_steps_initial():
    dag = DAG(steps=[
        Step(id="a", title="A", tool="t", args={}, depends_on=[]),
        Step(id="b", title="B", tool="t", args={}, depends_on=[]),
        Step(id="c", title="C", tool="t", args={}, depends_on=["a", "b"]),
    ])
    ready = dag.ready_steps(completed=set())
    assert set(ready) == {"a", "b"}


def test_ready_steps_partial():
    dag = DAG(steps=[
        Step(id="a", title="A", tool="t", args={}, depends_on=[]),
        Step(id="b", title="B", tool="t", args={}, depends_on=[]),
        Step(id="c", title="C", tool="t", args={}, depends_on=["a", "b"]),
    ])
    # With only 'a' completed, 'b' still has no deps so it's ready.
    # 'c' is not ready because 'b' is not yet completed.
    ready = dag.ready_steps(completed={"a"})
    assert set(ready) == {"b"}
    # With both a and b completed, c is ready.
    ready = dag.ready_steps(completed={"a", "b"})
    assert ready == ["c"]


def test_detects_cycle():
    with pytest.raises(DAGValidationError):
        DAG(steps=[
            Step(id="a", title="A", tool="t", args={}, depends_on=["b"]),
            Step(id="b", title="B", tool="t", args={}, depends_on=["a"]),
        ]).validate()


def test_detects_missing_dependency():
    with pytest.raises(DAGValidationError):
        DAG(steps=[
            Step(id="a", title="A", tool="t", args={}, depends_on=["ghost"]),
        ]).validate()


def test_dag_apply_mutation_add():
    from breadmind.flow.dag import DAGMutation
    dag = DAG(steps=[Step(id="a", title="A", tool="t", args={}, depends_on=[])])
    mutated = dag.apply_mutation(DAGMutation(added=[{"id": "b", "title": "B", "tool": "t", "args": {}, "depends_on": ["a"]}]))
    assert len(mutated.steps) == 2
    assert mutated.topological_order() == ["a", "b"]


def test_dag_apply_mutation_remove():
    from breadmind.flow.dag import DAGMutation
    dag = DAG(steps=[
        Step(id="a", title="A", tool="t", args={}, depends_on=[]),
        Step(id="b", title="B", tool="t", args={}, depends_on=[]),
    ])
    mutated = dag.apply_mutation(DAGMutation(removed=["a"]))
    assert len(mutated.steps) == 1
    assert mutated.steps[0].id == "b"


def test_dag_apply_mutation_cycle_raises():
    from breadmind.flow.dag import DAGMutation
    dag = DAG(steps=[
        Step(id="a", title="A", tool="t", args={}, depends_on=[]),
        Step(id="b", title="B", tool="t", args={}, depends_on=["a"]),
    ])
    with pytest.raises(DAGValidationError):
        dag.apply_mutation(DAGMutation(modified=[{"id": "a", "title": "A", "tool": "t", "args": {}, "depends_on": ["b"]}]))


def test_detects_duplicate_step_id():
    with pytest.raises(DAGValidationError):
        DAG(steps=[
            Step(id="a", title="A1", tool="t", args={}, depends_on=[]),
            Step(id="a", title="A2", tool="t", args={}, depends_on=[]),
        ]).validate()
