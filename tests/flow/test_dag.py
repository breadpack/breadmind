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
    ready = dag.ready_steps(completed={"a"})
    assert ready == []
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


def test_detects_duplicate_step_id():
    with pytest.raises(DAGValidationError):
        DAG(steps=[
            Step(id="a", title="A1", tool="t", args={}, depends_on=[]),
            Step(id="a", title="A2", tool="t", args={}, depends_on=[]),
        ]).validate()
