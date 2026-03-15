import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ContainerResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    container_id: str = ""
    error: str = ""


class ContainerExecutor:
    """Execute commands in isolated Docker containers."""

    def __init__(self, default_image: str = "python:3.12-slim",
                 memory_limit: str = "512m", cpu_limit: float = 1.0,
                 default_timeout: int = 30):
        self._default_image = default_image
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._default_timeout = default_timeout
        self._client = None
        self._running_containers: dict[str, object] = {}

    def _get_client(self):
        if not self._client:
            try:
                import docker
                self._client = docker.from_env()
            except ImportError:
                raise RuntimeError("docker package not installed. Install with: pip install docker>=7.0")
            except Exception as e:
                raise RuntimeError(f"Failed to connect to Docker: {e}")
        return self._client

    async def run_command(self, command: str, image: str | None = None,
                          volumes: dict | None = None, env: dict | None = None,
                          timeout: int | None = None) -> ContainerResult:
        """Run a command in an isolated container."""
        client = self._get_client()
        img = image or self._default_image
        t = timeout or self._default_timeout

        try:
            container = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.containers.run(
                    img,
                    command=["sh", "-c", command],
                    detach=True,
                    auto_remove=False,
                    mem_limit=self._memory_limit,
                    nano_cpus=int(self._cpu_limit * 1e9),
                    network_mode="none",  # no network by default
                    volumes=volumes or {},
                    environment=env or {},
                    read_only=True,  # read-only root filesystem
                    tmpfs={"/tmp": "size=64M"},  # writable /tmp
                )
            )

            self._running_containers[container.id] = container

            try:
                exit_info = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda: container.wait()
                    ),
                    timeout=t
                )

                logs = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
                )

                exit_code = exit_info.get("StatusCode", -1)

                return ContainerResult(
                    stdout=logs,
                    exit_code=exit_code,
                    container_id=container.short_id,
                )
            except asyncio.TimeoutError:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: container.kill()
                )
                return ContainerResult(
                    error=f"Container timed out after {t}s",
                    exit_code=-1,
                    container_id=container.short_id,
                )
            finally:
                self._running_containers.pop(container.id, None)
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: container.remove(force=True)
                    )
                except Exception:
                    pass

        except Exception as e:
            return ContainerResult(error=str(e), exit_code=-1)

    async def run_mcp_server(self, name: str, command: str, args: list[str] | None = None,
                              image: str | None = None, env: dict | None = None,
                              ports: dict | None = None) -> str:
        """Run an MCP server in a container. Returns container_id."""
        client = self._get_client()
        img = image or self._default_image
        full_cmd = command
        if args:
            full_cmd += " " + " ".join(args)

        try:
            container = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.containers.run(
                    img,
                    command=["sh", "-c", full_cmd],
                    detach=True,
                    auto_remove=False,
                    mem_limit=self._memory_limit,
                    nano_cpus=int(self._cpu_limit * 1e9),
                    environment=env or {},
                    ports=ports or {},
                    labels={"breadmind.type": "mcp_server", "breadmind.name": name},
                )
            )
            self._running_containers[container.id] = container
            return container.short_id
        except Exception as e:
            raise RuntimeError(f"Failed to start MCP server '{name}': {e}")

    async def run_subagent(self, task: str, system_prompt: str = "",
                            image: str | None = None, env: dict | None = None,
                            timeout: int = 120) -> ContainerResult:
        """Run a sub-agent task in an isolated container."""
        # Build the command to run breadmind in CLI mode
        escaped_task = task.replace("'", "'\\''")
        escaped_prompt = system_prompt.replace("'", "'\\''")
        cmd = f"python -m breadmind.main --cli --task '{escaped_task}'"
        if system_prompt:
            cmd += f" --system-prompt '{escaped_prompt}'"

        return await self.run_command(
            command=cmd,
            image=image or "breadmind/tool-runner:latest",
            env=env,
            timeout=timeout,
        )

    def list_containers(self) -> list[dict]:
        """List running BreadMind containers."""
        try:
            client = self._get_client()
            containers = client.containers.list(
                filters={"label": "breadmind.type"}
            )
            return [
                {
                    "id": c.short_id,
                    "name": c.labels.get("breadmind.name", ""),
                    "type": c.labels.get("breadmind.type", ""),
                    "status": c.status,
                    "image": c.image.tags[0] if c.image.tags else str(c.image.id)[:12],
                }
                for c in containers
            ]
        except Exception:
            return []

    async def cleanup(self):
        """Stop and remove all running BreadMind containers."""
        for cid, container in list(self._running_containers.items()):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda c=container: c.remove(force=True)
                )
            except Exception:
                pass
        self._running_containers.clear()

    def get_status(self) -> dict:
        """Get container executor status."""
        docker_available = False
        try:
            client = self._get_client()
            client.ping()
            docker_available = True
        except Exception:
            pass

        return {
            "docker_available": docker_available,
            "default_image": self._default_image,
            "memory_limit": self._memory_limit,
            "cpu_limit": self._cpu_limit,
            "running_containers": len(self._running_containers),
            "containers": self.list_containers(),
        }
