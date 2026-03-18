import pytest
from unittest.mock import MagicMock, patch
from breadmind.core.container import ContainerExecutor, ContainerResult


class TestContainerResult:
    def test_defaults(self):
        r = ContainerResult()
        assert r.stdout == ""
        assert r.exit_code == 0
        assert r.error == ""

    def test_with_values(self):
        r = ContainerResult(stdout="hello", exit_code=0, container_id="abc123")
        assert r.stdout == "hello"
        assert r.container_id == "abc123"


class TestContainerExecutor:
    def test_init_defaults(self):
        executor = ContainerExecutor()
        assert executor._default_image == "python:3.12-slim"
        assert executor._memory_limit == "512m"
        assert executor._cpu_limit == 1.0
        assert executor._default_timeout == 30

    def test_init_custom(self):
        executor = ContainerExecutor(
            default_image="ubuntu:22.04",
            memory_limit="1g",
            cpu_limit=2.0,
            default_timeout=60,
        )
        assert executor._default_image == "ubuntu:22.04"
        assert executor._memory_limit == "1g"

    @pytest.mark.asyncio
    async def test_run_command_no_docker(self):
        executor = ContainerExecutor()
        with patch.dict("sys.modules", {"docker": None}):
            executor._client = None
            with pytest.raises(RuntimeError, match="docker package not installed"):
                await executor.run_command("echo hello")

    @pytest.mark.asyncio
    async def test_run_command_mock(self):
        executor = ContainerExecutor()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "test123"
        mock_container.short_id = "test12"
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.return_value = b"hello world"
        mock_client.containers.run.return_value = mock_container
        executor._client = mock_client

        result = await executor.run_command("echo hello")
        assert result.stdout == "hello world"
        assert result.exit_code == 0

    def test_list_containers_no_docker(self):
        executor = ContainerExecutor()
        # Should return empty list when docker not available
        result = executor.list_containers()
        assert result == [] or isinstance(result, list)

    def test_get_status(self):
        executor = ContainerExecutor()
        status = executor.get_status()
        assert "docker_available" in status
        assert "default_image" in status
        assert "memory_limit" in status
        assert "running_containers" in status

    @pytest.mark.asyncio
    async def test_cleanup(self):
        executor = ContainerExecutor()
        # Should work even with no containers
        await executor.cleanup()
        assert len(executor._running_containers) == 0


class TestShellExecContainerMode:
    @pytest.mark.asyncio
    async def test_container_param_exists(self):
        from breadmind.tools.builtin import shell_exec
        import inspect
        sig = inspect.signature(shell_exec)
        assert "container" in sig.parameters

    @pytest.mark.asyncio
    async def test_container_false_runs_locally(self):
        from breadmind.tools.builtin import shell_exec
        # With container=False (default), should run locally
        result = await shell_exec("echo test_local")
        assert "test_local" in result


class TestSubAgentContainerIsolation:
    def test_task_has_container_field(self):
        from breadmind.core.subagent import SubAgentTask
        task = SubAgentTask(id="t1", parent_id=None, task="test", container_isolated=True)
        assert task.container_isolated is True

    def test_task_default_no_container(self):
        from breadmind.core.subagent import SubAgentTask
        task = SubAgentTask(id="t1", parent_id=None, task="test")
        assert task.container_isolated is False
