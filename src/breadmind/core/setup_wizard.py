"""First-run setup wizard — guides users through initial configuration.

Detects first run, collects provider/API key, validates LLM connection,
then uses the LLM to auto-discover the infrastructure environment.
"""

import asyncio
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EnvironmentInfo:
    """Discovered infrastructure environment."""
    hostname: str = ""
    os_name: str = ""
    os_version: str = ""
    docker_available: bool = False
    docker_version: str = ""
    kubernetes_available: bool = False
    kubectl_version: str = ""
    k8s_contexts: list[str] = field(default_factory=list)
    k8s_current_context: str = ""
    proxmox_available: bool = False
    proxmox_hosts: list[str] = field(default_factory=list)
    openwrt_available: bool = False
    openwrt_hosts: list[str] = field(default_factory=list)
    python_version: str = ""
    git_available: bool = False
    ssh_available: bool = False
    network_interfaces: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hostname": self.hostname,
            "os": f"{self.os_name} {self.os_version}",
            "docker": {"available": self.docker_available, "version": self.docker_version},
            "kubernetes": {
                "available": self.kubernetes_available,
                "version": self.kubectl_version,
                "contexts": self.k8s_contexts,
                "current_context": self.k8s_current_context,
            },
            "proxmox": {"available": self.proxmox_available, "hosts": self.proxmox_hosts},
            "openwrt": {"available": self.openwrt_available, "hosts": self.openwrt_hosts},
            "tools": {
                "python": self.python_version,
                "git": self.git_available,
                "ssh": self.ssh_available,
            },
            "network_interfaces": self.network_interfaces,
        }

    def summary(self) -> str:
        """Human-readable summary of discovered environment."""
        lines = [f"Host: {self.hostname} ({self.os_name} {self.os_version})"]
        if self.docker_available:
            lines.append(f"Docker: {self.docker_version}")
        if self.kubernetes_available:
            ctx = f" (context: {self.k8s_current_context})" if self.k8s_current_context else ""
            lines.append(f"Kubernetes: {self.kubectl_version}{ctx}")
            if self.k8s_contexts:
                lines.append(f"  Contexts: {', '.join(self.k8s_contexts)}")
        if self.proxmox_available:
            lines.append(f"Proxmox: {', '.join(self.proxmox_hosts)}")
        if self.openwrt_available:
            lines.append(f"OpenWrt: {', '.join(self.openwrt_hosts)}")
        return "\n".join(lines)


PROVIDER_OPTIONS = [
    {"id": "gemini", "name": "Google Gemini", "env_key": "GEMINI_API_KEY",
     "models": ["gemini-2.5-flash", "gemini-2.5-pro"], "free_tier": True,
     "signup_url": "https://aistudio.google.com/apikey"},
    {"id": "claude", "name": "Anthropic Claude", "env_key": "ANTHROPIC_API_KEY",
     "models": ["claude-sonnet-4-6", "claude-haiku-4-5"], "free_tier": False,
     "signup_url": "https://console.anthropic.com/settings/keys"},
    {"id": "grok", "name": "xAI Grok", "env_key": "XAI_API_KEY",
     "models": ["grok-3", "grok-3-mini"], "free_tier": False,
     "signup_url": "https://console.x.ai/"},
    {"id": "ollama", "name": "Ollama (Local)", "env_key": None,
     "models": ["llama3.1", "mistral", "qwen2.5"], "free_tier": True,
     "signup_url": "https://ollama.com/download"},
]


def is_first_run(db) -> bool:
    """Check if setup has been completed."""
    # Synchronous check for file-based store
    if hasattr(db, '_data'):
        return db._data.get("setup_completed") is None
    return True  # If no store, assume first run


async def is_first_run_async(db) -> bool:
    """Async check if setup has been completed."""
    if db is None:
        return True
    try:
        val = await db.get_setting("setup_completed")
        return val is None
    except Exception:
        return True


async def mark_setup_complete(db):
    """Mark setup as completed."""
    if db:
        await db.set_setting("setup_completed", {"completed": True})


async def validate_api_key(provider_id: str, api_key: str) -> dict:
    """Validate an API key by making a lightweight API call."""
    import aiohttp
    try:
        if provider_id == "gemini":
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return {"valid": True}
                    return {"valid": False, "error": f"Invalid key (HTTP {resp.status})"}

        elif provider_id == "claude":
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return {"valid": True}
                    return {"valid": False, "error": f"Invalid key (HTTP {resp.status})"}

        elif provider_id == "grok":
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return {"valid": True}
                    return {"valid": False, "error": f"Invalid key (HTTP {resp.status})"}

        elif provider_id == "ollama":
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://localhost:11434/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        return {"valid": True}
                    return {"valid": False, "error": "Ollama not responding"}

        return {"valid": True}
    except aiohttp.ClientError as e:
        return {"valid": False, "error": f"Connection error: {e}"}
    except asyncio.TimeoutError:
        return {"valid": False, "error": "Connection timed out"}


async def discover_environment() -> EnvironmentInfo:
    """Auto-discover the local infrastructure environment."""
    env = EnvironmentInfo()
    env.hostname = platform.node()
    env.os_name = platform.system()
    env.os_version = platform.version()
    env.python_version = platform.python_version()

    # Docker
    env.docker_available, env.docker_version = await _check_command(
        ["docker", "version", "--format", "{{.Server.Version}}"]
    )

    # Kubernetes
    env.kubernetes_available, env.kubectl_version = await _check_command(
        ["kubectl", "version", "--client", "--short"]
    )
    if env.kubernetes_available:
        # Get contexts
        ok, output = await _check_command(
            ["kubectl", "config", "get-contexts", "-o", "name"]
        )
        if ok and output:
            env.k8s_contexts = [c.strip() for c in output.strip().split("\n") if c.strip()]
        # Current context
        ok, output = await _check_command(["kubectl", "config", "current-context"])
        if ok and output:
            env.k8s_current_context = output.strip()

    # Git
    env.git_available = (await _check_command(["git", "--version"]))[0]

    # SSH
    env.ssh_available = shutil.which("ssh") is not None

    # Network interfaces (basic)
    try:
        import socket
        env.network_interfaces = [
            name for name, _ in socket.if_nameindex()
        ] if hasattr(socket, 'if_nameindex') else []
    except Exception:
        pass

    return env


async def generate_recommendations(env: EnvironmentInfo, message_handler) -> str:
    """Use LLM to analyze environment and generate setup recommendations."""
    if not message_handler:
        return env.summary()

    prompt = (
        "You are BreadMind, an AI infrastructure agent. Analyze this environment "
        "and provide brief setup recommendations (what to monitor, potential issues, "
        "suggested MCP servers to install).\n\n"
        f"Environment:\n{env.summary()}\n\n"
        "Respond concisely in Korean. Focus on actionable recommendations."
    )

    try:
        if asyncio.iscoroutinefunction(message_handler):
            result = await message_handler(prompt, user="setup_wizard", channel="setup")
        else:
            result = message_handler(prompt, user="setup_wizard", channel="setup")
        return str(result)
    except Exception as e:
        logger.warning(f"LLM recommendation failed: {e}")
        return env.summary()


async def _check_command(cmd: list[str]) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return True, stdout.decode("utf-8", errors="replace").strip()
        return False, ""
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return False, ""


async def run_cli_wizard(db, config) -> bool:
    """Interactive CLI setup wizard. Returns True if setup completed."""
    print("\n" + "=" * 50)
    print("  BreadMind - Initial Setup")
    print("=" * 50)

    # Step 1: Provider selection
    print("\n  Select your LLM provider:\n")
    for i, p in enumerate(PROVIDER_OPTIONS, 1):
        free = " (free tier)" if p["free_tier"] else ""
        print(f"    {i}. {p['name']}{free}")
    print()

    try:
        choice = input("  Choice [1]: ").strip()
        idx = int(choice) - 1 if choice else 0
        if not (0 <= idx < len(PROVIDER_OPTIONS)):
            idx = 0
    except (ValueError, EOFError):
        idx = 0

    provider = PROVIDER_OPTIONS[idx]
    print(f"\n  Selected: {provider['name']}")

    # Step 2: API key
    if provider["env_key"]:
        existing = os.environ.get(provider["env_key"], "")
        if existing:
            print(f"  API key already set: {existing[:8]}***")
        else:
            print(f"\n  Get your API key at: {provider['signup_url']}")
            try:
                api_key = input(f"  Enter {provider['env_key']}: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Setup cancelled.")
                return False

            if api_key:
                # Validate
                print("  Validating...", end="", flush=True)
                result = await validate_api_key(provider["id"], api_key)
                if result["valid"]:
                    print(" OK")
                    os.environ[provider["env_key"]] = api_key
                    from breadmind.config import save_env_var
                    save_env_var(provider["env_key"], api_key)
                    if db:
                        try:
                            from breadmind.config import save_api_key_to_db
                            await save_api_key_to_db(db, provider["env_key"], api_key)
                        except Exception:
                            pass
                else:
                    print(f" FAILED: {result.get('error', 'unknown')}")
                    print("  You can set the key later in Settings.")

    # Step 3: Save provider config
    config.llm.default_provider = provider["id"]
    config.llm.default_model = provider["models"][0]
    if db:
        await db.set_setting("llm", {
            "default_provider": provider["id"],
            "default_model": provider["models"][0],
            "tool_call_max_turns": config.llm.tool_call_max_turns,
            "tool_call_timeout_seconds": config.llm.tool_call_timeout_seconds,
        })

    # Step 4: Environment discovery
    print("\n  Discovering environment...")
    env = await discover_environment()
    print(f"\n{env.summary()}")

    # Step 5: Mark complete
    await mark_setup_complete(db)
    print("\n  Setup complete! Starting BreadMind...\n")
    return True
