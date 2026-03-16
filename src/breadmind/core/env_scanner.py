"""Comprehensive environment scanner — discovers and memorizes the host system.

Runs on first startup (or on demand) to build a complete picture of:
- OS, CPU, memory, disk
- Installed CLI tools and package managers
- Infrastructure tools (Docker, K8s, Proxmox, etc.)
- Network configuration
- Running services

Results are stored as pinned episodic memories + KG entities
so the agent can reference them in future conversations.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Complete environment scan result."""
    # System
    hostname: str = ""
    os_name: str = ""
    os_version: str = ""
    os_arch: str = ""
    cpu_info: str = ""
    cpu_cores: int = 0
    memory_total_gb: float = 0.0
    memory_available_gb: float = 0.0

    # Disks
    disks: list[dict] = field(default_factory=list)  # [{drive, total_gb, free_gb, percent_used}]

    # Tools & Package Managers
    installed_tools: dict[str, str] = field(default_factory=dict)  # {tool_name: version}
    package_managers: list[str] = field(default_factory=list)

    # Infrastructure
    docker_version: str = ""
    k8s_version: str = ""
    k8s_contexts: list[str] = field(default_factory=list)
    k8s_current_context: str = ""

    # Network
    ip_addresses: list[str] = field(default_factory=list)
    open_listeners: list[dict] = field(default_factory=list)  # [{port, process}]

    # Services
    running_services: list[str] = field(default_factory=list)

    def to_memory_text(self) -> str:
        """Convert to structured text for memory storage."""
        lines = [
            f"## Host Environment: {self.hostname}",
            f"- OS: {self.os_name} {self.os_version} ({self.os_arch})",
            f"- CPU: {self.cpu_info} ({self.cpu_cores} cores)",
            f"- Memory: {self.memory_available_gb:.1f}GB available / {self.memory_total_gb:.1f}GB total",
        ]

        if self.disks:
            lines.append("- Disks:")
            for d in self.disks:
                lines.append(f"  - {d['drive']}: {d['free_gb']:.0f}GB free / {d['total_gb']:.0f}GB ({d['percent_used']:.0f}% used)")

        if self.installed_tools:
            lines.append(f"- Installed tools: {', '.join(sorted(self.installed_tools.keys()))}")

        if self.package_managers:
            lines.append(f"- Package managers: {', '.join(self.package_managers)}")

        if self.docker_version:
            lines.append(f"- Docker: {self.docker_version}")
        if self.k8s_version:
            ctx = f" (context: {self.k8s_current_context})" if self.k8s_current_context else ""
            lines.append(f"- Kubernetes: {self.k8s_version}{ctx}")
            if self.k8s_contexts:
                lines.append(f"  - Contexts: {', '.join(self.k8s_contexts)}")

        if self.ip_addresses:
            lines.append(f"- IP addresses: {', '.join(self.ip_addresses)}")

        if self.running_services:
            lines.append(f"- Notable services: {', '.join(self.running_services[:20])}")

        return "\n".join(lines)

    def to_keywords(self) -> list[str]:
        """Extract keywords for memory indexing."""
        kws = [self.hostname.lower(), self.os_name.lower()]
        kws.extend(self.installed_tools.keys())
        kws.extend(self.package_managers)
        if self.docker_version:
            kws.append("docker")
        if self.k8s_version:
            kws.append("kubernetes")
        kws.extend(self.ip_addresses)
        return list(set(kw for kw in kws if kw))


async def scan_environment() -> ScanResult:
    """Perform a comprehensive environment scan."""
    result = ScanResult()

    # Basic system info
    result.hostname = platform.node()
    result.os_name = platform.system()
    result.os_version = platform.version()
    result.os_arch = platform.machine()
    result.cpu_cores = os.cpu_count() or 0

    # Run all scans concurrently
    await asyncio.gather(
        _scan_cpu(result),
        _scan_memory(result),
        _scan_disks(result),
        _scan_tools(result),
        _scan_infra(result),
        _scan_network(result),
        _scan_services(result),
    )

    return result


async def _run_cmd(cmd: str, timeout: int = 10) -> tuple[bool, str]:
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


async def _scan_cpu(result: ScanResult):
    """Detect CPU model."""
    system = platform.system()
    if system == "Windows":
        ok, out = await _run_cmd('wmic cpu get Name /value')
        if ok:
            for line in out.splitlines():
                if line.startswith("Name="):
                    result.cpu_info = line.split("=", 1)[1].strip()
                    break
    elif system == "Darwin":
        ok, out = await _run_cmd('sysctl -n machdep.cpu.brand_string')
        if ok:
            result.cpu_info = out.strip()
    else:
        ok, out = await _run_cmd("grep 'model name' /proc/cpuinfo | head -1")
        if ok and ":" in out:
            result.cpu_info = out.split(":", 1)[1].strip()


async def _scan_memory(result: ScanResult):
    """Detect total and available memory."""
    system = platform.system()
    if system == "Windows":
        ok, out = await _run_cmd(
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
        ok, out = await _run_cmd("free -b | grep Mem")
        if ok and out:
            parts = out.split()
            if len(parts) >= 4:
                try:
                    result.memory_total_gb = int(parts[1]) / (1024**3)
                    result.memory_available_gb = int(parts[3]) / (1024**3)
                except (ValueError, IndexError):
                    pass


async def _scan_disks(result: ScanResult):
    """Detect disk usage."""
    system = platform.system()
    if system == "Windows":
        ok, out = await _run_cmd(
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
        ok, out = await _run_cmd("df -B1 --output=target,size,avail,pcent / /home 2>/dev/null || df -k /")
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


async def _scan_tools(result: ScanResult):
    """Detect installed CLI tools and package managers."""
    # Common tools to check
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

    # Package managers
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

    async def _check_tool(name, cmd):
        ok, out = await _run_cmd(cmd, timeout=5)
        if ok and out:
            # Extract first line, truncate
            version = out.splitlines()[0][:80]
            return name, version
        # Fallback: check if binary exists
        if shutil.which(name):
            return name, "installed"
        return name, None

    # Run all checks concurrently
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


async def _scan_infra(result: ScanResult):
    """Detect infrastructure tools (Docker, K8s)."""
    # Docker
    ok, out = await _run_cmd("docker version --format '{{.Server.Version}}' 2>/dev/null || docker --version")
    if ok:
        result.docker_version = out.splitlines()[0][:60]

    # Kubernetes
    ok, out = await _run_cmd("kubectl version --client --short 2>/dev/null || kubectl version --client")
    if ok:
        result.k8s_version = out.splitlines()[0][:80]

        ok2, out2 = await _run_cmd("kubectl config get-contexts -o name")
        if ok2 and out2:
            result.k8s_contexts = [c.strip() for c in out2.splitlines() if c.strip()]

        ok3, out3 = await _run_cmd("kubectl config current-context")
        if ok3:
            result.k8s_current_context = out3.strip()


async def _scan_network(result: ScanResult):
    """Detect IP addresses."""
    system = platform.system()
    if system == "Windows":
        ok, out = await _run_cmd(
            'powershell -Command "(Get-NetIPAddress -AddressFamily IPv4 '
            '| Where-Object {$_.IPAddress -ne \'127.0.0.1\'}).IPAddress"'
        )
        if ok:
            result.ip_addresses = [ip.strip() for ip in out.splitlines() if ip.strip()]
    else:
        ok, out = await _run_cmd("hostname -I 2>/dev/null || ifconfig | grep 'inet ' | awk '{print $2}'")
        if ok:
            result.ip_addresses = [ip.strip() for ip in out.split() if ip.strip() and ip != "127.0.0.1"]


async def _scan_services(result: ScanResult):
    """Detect notable running services."""
    system = platform.system()
    notable = {
        "nginx", "apache", "httpd", "postgres", "postgresql", "mysql", "mariadb",
        "redis", "mongodb", "docker", "containerd", "kubelet", "elasticsearch",
        "grafana", "prometheus", "jenkins", "gitlab", "node", "java", "dotnet",
        "sshd", "code", "pveproxy", "proxmox",
    }

    if system == "Windows":
        ok, out = await _run_cmd(
            'powershell -Command "Get-Process | Select-Object -Unique Name | Format-Table -HideTableHeaders"',
            timeout=15,
        )
        if ok:
            procs = {p.strip().lower() for p in out.splitlines() if p.strip()}
            result.running_services = sorted(procs & notable)
    else:
        ok, out = await _run_cmd("ps -eo comm --no-headers | sort -u", timeout=10)
        if ok:
            procs = {p.strip().lower() for p in out.splitlines() if p.strip()}
            result.running_services = sorted(procs & notable)


# Install command patterns — when detected in shell_exec output, trigger tool discovery
_INSTALL_PATTERNS = re.compile(
    r"(?:successfully installed|is already installed|"
    r"Setting up |Unpacking |installed successfully|"
    r"choco install|winget install|scoop install|"
    r"apt install|yum install|dnf install|brew install|"
    r"pip install|npm install|cargo install|go install|"
    r"Installation complete|installed \d+ package)",
    re.I,
)


async def detect_new_tool(command: str, output: str, semantic_memory) -> str | None:
    """Check if a shell command installed a new tool and update KG if so.

    Called after shell_exec completes. Returns tool name if detected, else None.
    Lightweight: no LLM, just pattern matching + shutil.which.
    """
    if not output or not semantic_memory:
        return None

    # Check if output looks like an install
    if not _INSTALL_PATTERNS.search(output):
        return None

    # Extract potential tool name from the command
    tool_name = _extract_tool_from_install_cmd(command)
    if not tool_name:
        return None

    # Verify the tool actually exists now
    if not shutil.which(tool_name):
        return None

    # Check if we already know about it
    entity_id = f"tool:{tool_name}"
    existing = await semantic_memory.get_entity(entity_id)
    if existing:
        return None  # Already known

    # Get version if possible
    version = "installed"
    try:
        ok, ver = await _run_cmd(f"{tool_name} --version", timeout=5)
        if ok and ver:
            version = ver.splitlines()[0][:80]
    except Exception:
        pass

    # Store in KG
    from breadmind.storage.models import KGEntity, KGRelation
    hostname = platform.node()

    await semantic_memory.add_entity(KGEntity(
        id=entity_id,
        entity_type="infra_component",
        name=tool_name,
        properties={"version": version, "host": hostname, "discovered": "runtime"},
    ))
    await semantic_memory.add_relation(KGRelation(
        source_id=f"host:{hostname}",
        target_id=entity_id,
        relation_type="has_tool",
    ))

    logger.info("New tool discovered at runtime: %s (%s)", tool_name, version)
    return tool_name


def _extract_tool_from_install_cmd(command: str) -> str | None:
    """Extract the tool/package name from an install command."""
    # Match common install patterns
    patterns = [
        # pip install <pkg>
        re.compile(r"pip3?\s+install\s+(?:-[^\s]+\s+)*([a-zA-Z0-9_-]+)", re.I),
        # npm install -g <pkg>
        re.compile(r"npm\s+install\s+(?:-[^\s]+\s+)*([a-zA-Z0-9@/_-]+)", re.I),
        # apt/yum/dnf install <pkg>
        re.compile(r"(?:apt|yum|dnf|apt-get)\s+install\s+(?:-[^\s]+\s+)*([a-zA-Z0-9._-]+)", re.I),
        # brew install <pkg>
        re.compile(r"brew\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        # choco install <pkg>
        re.compile(r"choco\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        # winget install <pkg>
        re.compile(r"winget\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        # scoop install <pkg>
        re.compile(r"scoop\s+install\s+([a-zA-Z0-9._-]+)", re.I),
        # cargo install <pkg>
        re.compile(r"cargo\s+install\s+([a-zA-Z0-9_-]+)", re.I),
        # go install <pkg>
        re.compile(r"go\s+install\s+([a-zA-Z0-9./_-]+)", re.I),
    ]
    for pat in patterns:
        m = pat.search(command)
        if m:
            name = m.group(1).split("/")[-1].split("@")[0]  # Strip scope/version
            return name
    return None


async def scan_dynamic(include_tools: bool = False) -> ScanResult:
    """Lightweight scan of only dynamic (changing) data: memory, disks, IPs, services.

    Args:
        include_tools: If True, also rescan installed tools (slower, ~5s).
    """
    result = ScanResult()
    result.hostname = platform.node()
    result.os_name = platform.system()
    result.os_version = platform.version()
    result.os_arch = platform.machine()
    result.cpu_cores = os.cpu_count() or 0

    tasks = [
        _scan_memory(result),
        _scan_disks(result),
        _scan_network(result),
        _scan_services(result),
    ]
    if include_tools:
        tasks.append(_scan_tools(result))
        tasks.append(_scan_infra(result))

    await asyncio.gather(*tasks)

    return result


async def store_scan_in_memory(
    scan: ScanResult,
    episodic_memory,
    semantic_memory,
    db=None,
) -> dict:
    """Store scan results as pinned memories and KG entities.

    If an env_scan note already exists, it is replaced (not duplicated).
    KG entities are upserted (add_entity overwrites by ID).

    Returns stats about what was stored.
    """
    from breadmind.storage.models import KGEntity, KGRelation

    stored = {"notes": 0, "entities": 0, "updated": False}

    # 1. Find and replace existing env_scan note, or create new
    existing_note = None
    for note in episodic_memory._notes:
        if "env_scan" in (note.tags or []):
            existing_note = note
            break

    if existing_note is not None:
        # Update in place — preserve pin status and access history
        existing_note.content = scan.to_memory_text()
        existing_note.keywords = scan.to_keywords()
        existing_note.context_description = f"Environment scan of {scan.hostname}"
        from datetime import datetime, timezone
        existing_note.updated_at = datetime.now(timezone.utc)
        stored["updated"] = True
    else:
        note = await episodic_memory.add_note(
            content=scan.to_memory_text(),
            keywords=scan.to_keywords(),
            tags=["env_scan", "system_info", "pinned"],
            context_description=f"Environment scan of {scan.hostname}",
        )
        episodic_memory.pin_note(note)
    stored["notes"] = 1

    # 2. Upsert KG entities for the host
    host_entity = KGEntity(
        id=f"host:{scan.hostname}",
        entity_type="infra_component",
        name=scan.hostname,
        properties={
            "os": f"{scan.os_name} {scan.os_version}",
            "arch": scan.os_arch,
            "cpu": scan.cpu_info,
            "cpu_cores": scan.cpu_cores,
            "memory_total_gb": round(scan.memory_total_gb, 1),
            "memory_available_gb": round(scan.memory_available_gb, 1),
        },
    )
    await semantic_memory.add_entity(host_entity)
    stored["entities"] += 1

    # 3. Upsert entities for each IP address
    # Remove old IP relations first to handle IP changes
    old_rels = await semantic_memory.get_relations(f"host:{scan.hostname}")
    old_ip_ids = {r.target_id for r in old_rels if r.relation_type == "has_address"}
    new_ip_ids = {f"ip:{ip}" for ip in scan.ip_addresses}

    # Remove stale IP entities
    for stale_id in old_ip_ids - new_ip_ids:
        semantic_memory._entities.pop(stale_id, None)

    for ip in scan.ip_addresses:
        ip_entity = KGEntity(
            id=f"ip:{ip}",
            entity_type="infra_component",
            name=ip,
            properties={"type": "ip_address", "host": scan.hostname},
        )
        await semantic_memory.add_entity(ip_entity)
        # Only add relation if it doesn't already exist
        if f"ip:{ip}" not in old_ip_ids:
            await semantic_memory.add_relation(KGRelation(
                source_id=f"host:{scan.hostname}",
                target_id=f"ip:{ip}",
                relation_type="has_address",
            ))
        stored["entities"] += 1

    # 4. Upsert entities for infrastructure tools
    for tool_name in ["docker", "kubernetes"]:
        version = ""
        if tool_name == "docker" and scan.docker_version:
            version = scan.docker_version
        elif tool_name == "kubernetes" and scan.k8s_version:
            version = scan.k8s_version
        else:
            continue

        tool_entity = KGEntity(
            id=f"tool:{tool_name}",
            entity_type="infra_component",
            name=tool_name,
            properties={"version": version, "host": scan.hostname},
        )
        await semantic_memory.add_entity(tool_entity)
        stored["entities"] += 1

    # 5. Upsert entities for disks (with latest usage)
    for disk in scan.disks:
        disk_entity = KGEntity(
            id=f"disk:{scan.hostname}:{disk['drive']}",
            entity_type="infra_component",
            name=f"{scan.hostname}:{disk['drive']}",
            properties={
                "total_gb": round(disk["total_gb"], 1),
                "free_gb": round(disk["free_gb"], 1),
                "percent_used": round(disk["percent_used"], 1),
            },
        )
        await semantic_memory.add_entity(disk_entity)
        stored["entities"] += 1

    # 6. Save scan timestamp in DB
    if db:
        try:
            from datetime import datetime, timezone
            await db.set_setting("last_env_scan", {
                "hostname": scan.hostname,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tools_count": len(scan.installed_tools),
                "disks_count": len(scan.disks),
            })
        except Exception:
            pass

    action = "updated" if stored["updated"] else "stored"
    logger.info(
        "Environment scan %s: %d notes, %d entities (host=%s, tools=%d, disks=%d)",
        action, stored["notes"], stored["entities"],
        scan.hostname, len(scan.installed_tools), len(scan.disks),
    )

    return stored
