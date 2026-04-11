import pytest

from breadmind.flow.dag_generator import DAGGenerator, DAGGenerationError


class FakeLLM:
    def __init__(self, response):
        self.response = response

    async def chat(self, messages, **kwargs):
        return type("Resp", (), {"content": self.response})()


async def test_generate_dag_from_request():
    llm = FakeLLM('{"steps":[{"id":"s1","title":"Hello","tool":"shell_exec","args":{"cmd":"echo hi"},"depends_on":[]}]}')
    gen = DAGGenerator(llm=llm)
    dag = await gen.generate(
        title="Test task",
        description="Echo hi",
        available_tools=["shell_exec"],
    )
    assert len(dag.steps) == 1
    assert dag.steps[0].tool == "shell_exec"


async def test_generator_strips_markdown_fences():
    llm = FakeLLM('```json\n{"steps":[{"id":"s1","title":"Hello","tool":"shell_exec","args":{},"depends_on":[]}]}\n```')
    gen = DAGGenerator(llm=llm)
    dag = await gen.generate(title="T", description="D", available_tools=["shell_exec"])
    assert len(dag.steps) == 1


async def test_generator_rejects_invalid_json():
    llm = FakeLLM("not json")
    gen = DAGGenerator(llm=llm)
    with pytest.raises(DAGGenerationError):
        await gen.generate(title="T", description="D", available_tools=["shell_exec"])


async def test_generator_rejects_unknown_tool():
    llm = FakeLLM('{"steps":[{"id":"s1","title":"T","tool":"unknown_tool","args":{},"depends_on":[]}]}')
    gen = DAGGenerator(llm=llm)
    with pytest.raises(DAGGenerationError):
        await gen.generate(title="T", description="D", available_tools=["shell_exec"])


async def test_generator_rejects_empty_steps():
    llm = FakeLLM('{"steps":[]}')
    gen = DAGGenerator(llm=llm)
    with pytest.raises(DAGGenerationError):
        await gen.generate(title="T", description="D", available_tools=["shell_exec"])


async def test_generator_rejects_cycle():
    llm = FakeLLM('{"steps":[{"id":"a","title":"A","tool":"shell_exec","args":{},"depends_on":["b"]},{"id":"b","title":"B","tool":"shell_exec","args":{},"depends_on":["a"]}]}')
    gen = DAGGenerator(llm=llm)
    with pytest.raises(DAGGenerationError):
        await gen.generate(title="T", description="D", available_tools=["shell_exec"])
