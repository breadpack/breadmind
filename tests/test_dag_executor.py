import pytest
from breadmind.core.dag_executor import DAGExecutor
from breadmind.core.planner import TaskDAG, TaskNode
from breadmind.core.result_evaluator import ResultEvaluator
from breadmind.core.subagent import SubAgentResult


def _make_dag(nodes_spec: list[tuple]) -> TaskDAG:
    """Helper: nodes_spec = [(id, role, depends_on, difficulty), ...]"""
    dag = TaskDAG(goal="test goal")
    for nid, role, deps, diff in nodes_spec:
        dag.nodes[nid] = TaskNode(
            id=nid, description=f"Do {nid}", role=role,
            depends_on=deps, difficulty=diff, expected_output=f"Result of {nid}",
        )
    return dag


@pytest.mark.asyncio
async def test_linear_dag_executes_in_order():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
        ("t2", "k8s_executor", ["t1"], "medium"),
    ])
    execution_order = []

    async def mock_spawn(node, context):
        execution_order.append(node.id)
        return SubAgentResult(task_id=node.id, success=True, output=f"done-{node.id}", turns_used=1)

    executor = DAGExecutor(subagent_factory=mock_spawn, evaluator=ResultEvaluator())
    results = await executor.execute(dag)
    assert execution_order == ["t1", "t2"]
    assert results["t1"].success is True
    assert results["t2"].success is True


@pytest.mark.asyncio
async def test_parallel_dag_runs_concurrently():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
        ("t2", "proxmox_diagnostician", [], "low"),
        ("t3", "general_analyst", ["t1", "t2"], "medium"),
    ])

    async def mock_spawn(node, context):
        return SubAgentResult(task_id=node.id, success=True, output=f"done-{node.id}", turns_used=1)

    executor = DAGExecutor(subagent_factory=mock_spawn, evaluator=ResultEvaluator())
    results = await executor.execute(dag)
    assert "t1" in dag.context
    assert "t2" in dag.context
    assert results["t3"].success is True


@pytest.mark.asyncio
async def test_failed_task_returns_abnormal():
    dag = _make_dag([("t1", "k8s_diagnostician", [], "low")])

    async def mock_spawn(node, context):
        return SubAgentResult(task_id=node.id, success=False, output="[success=False] Connection refused", turns_used=1)

    executor = DAGExecutor(subagent_factory=mock_spawn, evaluator=ResultEvaluator())
    results = await executor.execute(dag)
    assert results["t1"].success is False


@pytest.mark.asyncio
async def test_dag_context_propagation():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
        ("t2", "k8s_executor", ["t1"], "medium"),
    ])
    received_contexts = {}

    async def mock_spawn(node, context):
        received_contexts[node.id] = dict(context)
        return SubAgentResult(task_id=node.id, success=True, output=f"result-{node.id}", turns_used=1)

    executor = DAGExecutor(subagent_factory=mock_spawn, evaluator=ResultEvaluator())
    await executor.execute(dag)
    assert received_contexts["t1"] == {}
    assert "t1" in received_contexts["t2"]
    assert received_contexts["t2"]["t1"] == "result-t1"


@pytest.mark.asyncio
async def test_dependency_failure_skips_downstream():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
        ("t2", "k8s_executor", ["t1"], "medium"),
    ])

    async def mock_spawn(node, context):
        return SubAgentResult(task_id=node.id, success=False, output="[success=False] Error", turns_used=1)

    executor = DAGExecutor(subagent_factory=mock_spawn, evaluator=ResultEvaluator())
    results = await executor.execute(dag)
    assert results["t1"].success is False
    assert results["t2"].success is False
    assert "dependency failed" in results["t2"].output.lower()
