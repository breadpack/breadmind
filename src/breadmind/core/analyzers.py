"""K8sGPT-style lightweight analyzers — diagnose without LLM calls."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticResult:
    source: str  # "k8s", "proxmox", "openwrt", "system"
    severity: str  # "info", "warning", "critical"
    title: str
    details: str
    suggestion: str = ""


class BaseAnalyzer:
    """Base class for infrastructure analyzers."""
    name: str = "base"
    source: str = "system"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        raise NotImplementedError


class DiskUsageAnalyzer(BaseAnalyzer):
    name = "disk_usage"
    source = "system"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        results = []
        try:
            output = await tool_executor("shell_exec", {"command": "df -h --output=pcent,target 2>/dev/null || wmic logicaldisk get size,freespace,caption"})
            if not output.success:
                return results
            for line in output.output.split("\n"):
                match = re.search(r"(\d+)%\s+(.+)", line.strip())
                if match:
                    usage = int(match.group(1))
                    mount = match.group(2).strip()
                    if usage >= 90:
                        results.append(DiagnosticResult(
                            source="system", severity="critical",
                            title=f"Disk almost full: {mount} ({usage}%)",
                            details=f"Mount point {mount} is at {usage}% capacity.",
                            suggestion=f"Clean up disk space on {mount} or extend the volume.",
                        ))
                    elif usage >= 80:
                        results.append(DiagnosticResult(
                            source="system", severity="warning",
                            title=f"Disk usage high: {mount} ({usage}%)",
                            details=f"Mount point {mount} is at {usage}% capacity.",
                            suggestion=f"Monitor disk usage on {mount}.",
                        ))
        except Exception as e:
            logger.debug(f"DiskUsageAnalyzer error: {e}")
        return results


class MemoryUsageAnalyzer(BaseAnalyzer):
    name = "memory_usage"
    source = "system"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        results = []
        try:
            output = await tool_executor("shell_exec", {"command": "free -m 2>/dev/null || systeminfo | findstr Memory"})
            if not output.success:
                return results
            # Parse Linux 'free' output
            for line in output.output.split("\n"):
                if line.startswith("Mem:"):
                    parts = line.split()
                    if len(parts) >= 3:
                        total = int(parts[1])
                        used = int(parts[2])
                        pct = (used / total * 100) if total > 0 else 0
                        if pct >= 90:
                            results.append(DiagnosticResult(
                                source="system", severity="critical",
                                title=f"Memory critically low ({pct:.0f}% used)",
                                details=f"Used: {used}MB / {total}MB",
                                suggestion="Identify and stop memory-heavy processes, or add more RAM.",
                            ))
                        elif pct >= 80:
                            results.append(DiagnosticResult(
                                source="system", severity="warning",
                                title=f"Memory usage high ({pct:.0f}% used)",
                                details=f"Used: {used}MB / {total}MB",
                                suggestion="Monitor memory usage trends.",
                            ))
        except Exception as e:
            logger.debug(f"MemoryUsageAnalyzer error: {e}")
        return results


class K8sPodAnalyzer(BaseAnalyzer):
    name = "k8s_pods"
    source = "k8s"

    async def analyze(self, tool_executor) -> list[DiagnosticResult]:
        results = []
        try:
            output = await tool_executor("shell_exec", {
                "command": "kubectl get pods --all-namespaces --field-selector=status.phase!=Running,status.phase!=Succeeded -o wide 2>/dev/null"
            })
            if not output.success or "No resources" in output.output:
                return results
            lines = [line for line in output.output.strip().split("\n") if line and not line.startswith("NAMESPACE")]
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    ns, pod, ready, status = parts[0], parts[1], parts[2], parts[3]
                    if status in ("CrashLoopBackOff", "Error", "OOMKilled", "ImagePullBackOff"):
                        results.append(DiagnosticResult(
                            source="k8s", severity="critical",
                            title=f"Pod {ns}/{pod} in {status}",
                            details=f"Ready: {ready}, Status: {status}",
                            suggestion=f"kubectl describe pod {pod} -n {ns} && kubectl logs {pod} -n {ns} --tail=50",
                        ))
                    elif status == "Pending":
                        results.append(DiagnosticResult(
                            source="k8s", severity="warning",
                            title=f"Pod {ns}/{pod} stuck Pending",
                            details=f"Ready: {ready}",
                            suggestion=f"Check resource quotas and node capacity: kubectl describe pod {pod} -n {ns}",
                        ))
        except Exception as e:
            logger.debug(f"K8sPodAnalyzer error: {e}")
        return results


# Registry of all analyzers
ALL_ANALYZERS: list[type[BaseAnalyzer]] = [
    DiskUsageAnalyzer,
    MemoryUsageAnalyzer,
    K8sPodAnalyzer,
]


async def run_all_analyzers(tool_executor) -> list[DiagnosticResult]:
    """Run all registered analyzers and collect results."""
    all_results = []
    tasks = [cls().analyze(tool_executor) for cls in ALL_ANALYZERS]
    for coro in asyncio.as_completed(tasks):
        try:
            results = await coro
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"Analyzer failed: {e}")
    # Sort by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    all_results.sort(key=lambda r: severity_order.get(r.severity, 3))
    return all_results
