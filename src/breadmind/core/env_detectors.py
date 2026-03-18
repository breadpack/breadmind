"""Environment detection functions — system info, tools, network, services.

Extracted from env_scanner.py for SRP compliance.
Each function populates a subset of ScanResult fields.
"""
from __future__ import annotations

import asyncio
import platform
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.core.env_scanner import ScanResult


async def run_cmd(cmd: str, timeout: int = 10) -> tuple[bool, str]:
    """Run a shell command and return (success, output)."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return True, stdout.decode("utf-8", errors="replace").strip()
        return False, ""
    except (asyncio.TimeoutError, OSError, Exception):
        return False, ""


async def scan_cpu(result: ScanResult) -> None:
    """Detect CPU model."""
    system = platform.system()
    if system == "Windows":
        ok, out = await run_cmd('wmic cpu get Name /value')
        if ok:
            for line in out.splitlines():
                if line.startswith("Name="):
                    result.cpu_info = line.split("=", 1)[1].strip()
                    break
    elif system == "Darwin":
        ok, out = await run_cmd('sysctl -n machdep.cpu.brand_string')
        if ok:
            result.cpu_info = out.strip()
    else:
        ok, out = await run_cmd("grep 'model name' /proc/cpuinfo | head -1")
        if ok and ":" in out:
            result.cpu_info = out.split(":", 1)[1].strip()


async def scan_memory(result: ScanResult) -> None:
    """Detect total and available memory."""
    system = platform.system()
    if system == "Windows":
        ok, out = await run_cmd(
            'powershell -Command "Get-CimInstance Win32_OperatingSystem | '
            'Select-Object TotalVisibleMemorySize,FreePhysicalMemory | '
            'Format-List"'
        )
        if ok:
            for line in out.splitlines():
                line = line.strip()
                if "TotalVisibleMemorySize" in line and ":" in line:
                    try:
                        kb = int(line.split(":", 1)[1].strip())
                        result.memory_total_gb = kb / (1024 * 1024)
                    except ValueError:
                        pass
                elif "FreePhysicalMemory" in line and ":" in line:
                    try:
                        kb = int(line.split(":", 1)[1].strip())
                        result.memory_available_gb = kb / (1024 * 1024)
                    except ValueError:
                        pass
    else:
        ok, out = await run_cmd("free -b | grep Mem")
        if ok and out:
            parts = out.split()
            if len(parts) >= 4:
                try:
                    result.memory_total_gb = int(parts[1]) / (1024**3)
                    result.memory_available_gb = int(parts[3]) / (1024**3)
                except (ValueError, IndexError):
                    pass


async def scan_disks(result: ScanResult) -> None:
    """Detect disk usage."""
    system = platform.system()
    if system == "Windows":
        ok, out = await run_cmd(
            'powershell -Command "Get-PSDrive -PSProvider FileSystem | '
            'Select-Object Name,Used,Free | Format-Table -AutoSize"'
        )
        if ok:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and len(parts[0]) == 1 and parts[0].isalpha():
                    try:
                        used = int(parts[1])
                        free = int(parts[2])
                        total = used + free
                        if total > 0:
                            result.disks.append({
                                "drive": f"{parts[0]}:",
                                "total_gb": total / (1024**3),
                                "free_gb": free / (1024**3),
                                "percent_used": (used / total) * 100,
                            })
                    except (ValueError, ZeroDivisionError):
                        pass
    else:
        ok, out = await run_cmd("df -B1 --output=target,size,avail,pcent / /home 2>/dev/null || df -k /")
        if ok:
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        mount = parts[0]
                        total = int(parts[1]) / (1024**3)
                        avail = int(parts[2]) / (1024**3)
                        pct = parts[3].rstrip('%')
                        result.disks.append({
                            "drive": mount,
                            "total_gb": total,
                            "free_gb": avail,
                            "percent_used": float(pct),
                        })
                    except (ValueError, IndexError):
                        pass


async def scan_tools(result: ScanResult) -> None:
    """Detect installed CLI tools and package managers."""
    tools = {
        "git": "git --version",
        "python": "python --version",
        "node": "node --version",
        "npm": "npm --version",
        "go": "go version",
        "rust": "rustc --version",
        "java": "java -version 2>&1",
        "dotnet": "dotnet --version",
        "terraform": "terraform --version",
        "ansible": "ansible --version",
        "helm": "helm version --short",
        "curl": "curl --version",
        "wget": "wget --version",
        "ssh": "ssh -V 2>&1",
        "nginx": "nginx -v 2>&1",
        "postgres": "psql --version",
        "redis": "redis-cli --version",
        "mysql": "mysql --version",
    }

    pkg_mgrs = {
        "apt": "apt --version",
        "yum": "yum --version",
        "dnf": "dnf --version",
        "brew": "brew --version",
        "choco": "choco --version",
        "winget": "winget --version",
        "scoop": "scoop --version",
        "pip": "pip --version",
        "conda": "conda --version",
    }

    async def _check_tool(name: str, cmd: str):
        ok, out = await run_cmd(cmd, timeout=5)
        if ok and out:
            version = out.splitlines()[0][:80]
            return name, version
        if shutil.which(name):
            return name, "installed"
        return name, None

    tool_tasks = [_check_tool(name, cmd) for name, cmd in tools.items()]
    pkg_tasks = [_check_tool(name, cmd) for name, cmd in pkg_mgrs.items()]
    all_results = await asyncio.gather(*tool_tasks, *pkg_tasks)

    tool_names = set(tools.keys())
    for name, version in all_results:
        if version is None:
            continue
        if name in tool_names:
            result.installed_tools[name] = version
        else:
            result.package_managers.append(name)


async def scan_infra(result: ScanResult) -> None:
    """Detect infrastructure tools (Docker, K8s)."""
    ok, out = await run_cmd("docker version --format '{{.Server.Version}}' 2>/dev/null || docker --version")
    if ok:
        result.docker_version = out.splitlines()[0][:60]

    ok, out = await run_cmd("kubectl version --client --short 2>/dev/null || kubectl version --client")
    if ok:
        result.k8s_version = out.splitlines()[0][:80]

        ok2, out2 = await run_cmd("kubectl config get-contexts -o name")
        if ok2 and out2:
            result.k8s_contexts = [c.strip() for c in out2.splitlines() if c.strip()]

        ok3, out3 = await run_cmd("kubectl config current-context")
        if ok3:
            result.k8s_current_context = out3.strip()


async def scan_network(result: ScanResult) -> None:
    """Detect IP addresses."""
    system = platform.system()
    if system == "Windows":
        ok, out = await run_cmd(
            'powershell -Command "(Get-NetIPAddress -AddressFamily IPv4 '
            '| Where-Object {$_.IPAddress -ne \'127.0.0.1\'}).IPAddress"'
        )
        if ok:
            result.ip_addresses = [ip.strip() for ip in out.splitlines() if ip.strip()]
    else:
        ok, out = await run_cmd("hostname -I 2>/dev/null || ifconfig | grep 'inet ' | awk '{print $2}'")
        if ok:
            result.ip_addresses = [ip.strip() for ip in out.split() if ip.strip() and ip != "127.0.0.1"]


async def scan_services(result: ScanResult) -> None:
    """Detect notable running services."""
    notable = {
        "nginx", "apache", "httpd", "postgres", "postgresql", "mysql", "mariadb",
        "redis", "mongodb", "docker", "containerd", "kubelet", "elasticsearch",
        "grafana", "prometheus", "jenkins", "gitlab", "node", "java", "dotnet",
        "sshd", "code", "pveproxy", "proxmox",
    }

    system = platform.system()
    if system == "Windows":
        ok, out = await run_cmd(
            'powershell -Command "Get-Process | Select-Object -Unique Name | Format-Table -HideTableHeaders"',
            timeout=15,
        )
        if ok:
            procs = {p.strip().lower() for p in out.splitlines() if p.strip()}
            result.running_services = sorted(procs & notable)
    else:
        ok, out = await run_cmd("ps -eo comm --no-headers | sort -u", timeout=10)
        if ok:
            procs = {p.strip().lower() for p in out.splitlines() if p.strip()}
            result.running_services = sorted(procs & notable)
