"""v2 CLI 진입점: breadmind run/create 명령."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BreadMind v2 Agent Framework")
    sub = parser.add_subparsers(dest="command")

    # breadmind run <agent.yaml> [--runtime cli|server] [--port 8080]
    run_parser = sub.add_parser("run", help="Run an agent from YAML definition")
    run_parser.add_argument("agent_file", help="Path to agent YAML file")
    run_parser.add_argument("--runtime", default="cli", choices=["cli", "server"],
                           help="Runtime mode (default: cli)")
    run_parser.add_argument("--host", default="0.0.0.0", help="Server host (server mode)")
    run_parser.add_argument("--port", type=int, default=8080, help="Server port (server mode)")

    # breadmind create <description>
    create_parser = sub.add_parser("create", help="Create agent YAML from description")
    create_parser.add_argument("description", help="Natural language agent description")
    create_parser.add_argument("--output", "-o", default=None, help="Output YAML path")

    return parser.parse_args(args)


def run_command(args: argparse.Namespace) -> None:
    """Execute `breadmind run` command."""
    agent_path = Path(args.agent_file)
    if not agent_path.exists():
        print(f"Error: Agent file not found: {agent_path}")
        sys.exit(1)

    from breadmind.sdk.agent import Agent
    agent = Agent.from_yaml(str(agent_path))

    asyncio.run(agent.serve(
        runtime=args.runtime,
        host=getattr(args, "host", "0.0.0.0"),
        port=getattr(args, "port", 8080),
    ))


def create_command(args: argparse.Namespace) -> None:
    """Execute `breadmind create` command (stub — generates basic YAML)."""
    import re
    description = args.description

    # Simple heuristic: extract domain hints
    name = "CustomAgent"
    tools = ["shell_exec", "file_read", "web_search"]
    role = None

    if re.search(r"k8s|kubernetes|pod|deploy", description, re.I):
        name = "K8sAgent"
        tools.extend(["k8s_pods_list", "k8s_pods_get", "k8s_pods_log", "k8s_nodes_top"])
        role = "k8s_expert"
    elif re.search(r"proxmox|vm|lxc|hypervisor", description, re.I):
        name = "ProxmoxAgent"
        tools.extend(["proxmox_get_vms", "proxmox_get_vm_status"])
        role = "proxmox_expert"
    elif re.search(r"openwrt|router|firewall|network", description, re.I):
        name = "NetworkAgent"
        tools.extend(["openwrt_network_status", "openwrt_system_status"])
        role = "openwrt_expert"

    yaml_content = f"""name: {name}
config:
  provider: claude
  model: claude-sonnet-4-6
  max_turns: 10

prompt:
  persona: professional
  language: ko
{f'  role: {role}' if role else ''}

memory:
  working: true
  episodic: true
  dream: true

tools:
  include: [{', '.join(tools)}]

safety:
  autonomy: confirm-destructive
"""

    output_path = args.output or f"agents/{name.lower()}.yaml"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(yaml_content, encoding="utf-8")
    print(f"Agent YAML created: {output_path}")


def main(args: list[str] | None = None) -> None:
    parsed = _parse_args(args)
    if parsed.command == "run":
        run_command(parsed)
    elif parsed.command == "create":
        create_command(parsed)
    else:
        _parse_args(["--help"])
