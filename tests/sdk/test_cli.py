import pytest
from pathlib import Path
from breadmind.sdk.cli import _parse_args, create_command


def test_parse_run_args():
    args = _parse_args(["run", "agent.yaml"])
    assert args.command == "run"
    assert args.agent_file == "agent.yaml"
    assert args.runtime == "cli"


def test_parse_run_server():
    args = _parse_args(["run", "agent.yaml", "--runtime", "server", "--port", "9000"])
    assert args.runtime == "server"
    assert args.port == 9000


def test_parse_create_args():
    args = _parse_args(["create", "K8s 장애 진단 에이전트"])
    assert args.command == "create"
    assert "K8s" in args.description


def test_create_k8s_agent(tmp_path):
    output = tmp_path / "test_agent.yaml"
    args = _parse_args(["create", "Kubernetes pod 진단 에이전트", "-o", str(output)])
    create_command(args)
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "K8sAgent" in content
    assert "k8s_pods_list" in content
    assert "k8s_expert" in content


def test_create_proxmox_agent(tmp_path):
    output = tmp_path / "proxmox.yaml"
    args = _parse_args(["create", "Proxmox VM 관리 에이전트", "-o", str(output)])
    create_command(args)
    content = output.read_text(encoding="utf-8")
    assert "ProxmoxAgent" in content


def test_create_generic_agent(tmp_path):
    output = tmp_path / "generic.yaml"
    args = _parse_args(["create", "일반 도우미 에이전트", "-o", str(output)])
    create_command(args)
    content = output.read_text(encoding="utf-8")
    assert "CustomAgent" in content
