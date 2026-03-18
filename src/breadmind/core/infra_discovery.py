# src/breadmind/core/infra_discovery.py
"""Infrastructure auto-discovery — scans local network for known services."""
from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Known service signatures: port → (service_type, service_name, verify_path)
SERVICE_SIGNATURES = {
    22: ("ssh", "SSH Server", None),
    53: ("dns", "DNS Server", None),
    80: ("http", "Web Server", None),
    443: ("https", "Web Server (HTTPS)", None),
    8006: ("proxmox", "Proxmox VE", "/api2/json/version"),
    8080: ("webui", "Web UI", None),
    6443: ("kubernetes", "Kubernetes API", "/api"),
    10250: ("kubelet", "Kubernetes Kubelet", None),
    5000: ("synology_http", "Synology DSM", None),
    5001: ("synology_https", "Synology DSM (HTTPS)", None),
    9090: ("prometheus", "Prometheus", None),
    3000: ("grafana", "Grafana", None),
    8081: ("misc", "Service (8081)", None),
    1883: ("mqtt", "MQTT Broker", None),
    8123: ("homeassistant", "Home Assistant", None),
    9100: ("node_exporter", "Node Exporter", None),
}

# OpenWrt detection: typically on port 80/443 at gateway IP with LuCI
OPENWRT_PATHS = ["/cgi-bin/luci", "/ubus"]


@dataclass
class DiscoveredService:
    host: str
    port: int
    service_type: str
    service_name: str
    reachable: bool = True
    response_time_ms: float = 0.0
    extra_info: dict = field(default_factory=dict)


@dataclass
class DiscoveryResult:
    hosts_scanned: int = 0
    services_found: list[DiscoveredService] = field(default_factory=list)
    scan_time_seconds: float = 0.0
    network: str = ""


async def check_port(host: str, port: int, timeout: float = 1.0) -> tuple[bool, float]:
    """Check if a port is open on a host. Returns (open, response_time_ms)."""
    import time
    start = time.time()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        elapsed = (time.time() - start) * 1000
        writer.close()
        await writer.wait_closed()
        return True, elapsed
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False, 0.0


async def identify_service(host: str, port: int) -> DiscoveredService | None:
    """Check if a known service is running on host:port."""
    is_open, response_time = await check_port(host, port)
    if not is_open:
        return None

    sig = SERVICE_SIGNATURES.get(port)
    if sig:
        service_type, service_name, verify_path = sig
    else:
        service_type = "unknown"
        service_name = f"Service (port {port})"

    extra = {}

    # Try HTTP identification for web services
    if port in (80, 443, 8006, 5000, 5001, 8080, 8123, 3000, 9090):
        try:
            import aiohttp
            scheme = "https" if port in (443, 8006, 5001) else "http"
            url = f"{scheme}://{host}:{port}/"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3), ssl=False) as resp:
                    text = await resp.text()
                    headers = dict(resp.headers)

                    # Detect specific services from response
                    if "proxmox" in text.lower() or "pve" in text.lower():
                        service_type = "proxmox"
                        service_name = "Proxmox VE"
                    elif "synology" in text.lower() or "diskstation" in text.lower():
                        service_type = "synology"
                        service_name = "Synology DSM"
                    elif "luci" in text.lower() or "openwrt" in text.lower():
                        service_type = "openwrt"
                        service_name = "OpenWrt"
                    elif "home assistant" in text.lower() or "homeassistant" in text.lower():
                        service_type = "homeassistant"
                        service_name = "Home Assistant"
                    elif "grafana" in text.lower():
                        service_type = "grafana"
                        service_name = "Grafana"

                    extra["server"] = headers.get("Server", "")
                    extra["title"] = _extract_title(text)
        except Exception:
            pass

    return DiscoveredService(
        host=host,
        port=port,
        service_type=service_type,
        service_name=service_name,
        reachable=True,
        response_time_ms=response_time,
        extra_info=extra,
    )


async def scan_host(host: str, ports: list[int] | None = None) -> list[DiscoveredService]:
    """Scan a single host for known services."""
    if ports is None:
        ports = list(SERVICE_SIGNATURES.keys())

    tasks = [identify_service(host, port) for port in ports]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


async def discover_network(
    network: str | None = None,
    scan_range: int = 20,
    ports: list[int] | None = None,
) -> DiscoveryResult:
    """Scan local network for infrastructure services.

    If network is not specified, auto-detects the local network from default gateway.
    scan_range: number of IPs to scan from the network base (default 20 for speed).
    """
    import time
    start = time.time()

    if not network:
        network = _detect_network()

    result = DiscoveryResult(network=network)

    # Parse network and generate IP list
    ips = _generate_ips(network, scan_range)
    result.hosts_scanned = len(ips)

    # Scan all hosts in parallel
    all_tasks = []
    for ip in ips:
        all_tasks.append(scan_host(ip, ports))

    host_results = await asyncio.gather(*all_tasks)
    for services in host_results:
        result.services_found.extend(services)

    result.scan_time_seconds = time.time() - start
    logger.info(
        "Network scan complete: %d hosts, %d services found in %.1fs",
        result.hosts_scanned, len(result.services_found), result.scan_time_seconds,
    )
    return result


def _detect_network() -> str:
    """Auto-detect the local network (gateway-based)."""
    try:
        # Connect to a public DNS to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        # Assume /24 network
        parts = local_ip.rsplit(".", 1)
        return f"{parts[0]}.0/24"
    except Exception:
        return "192.168.1.0/24"


def _generate_ips(network: str, count: int) -> list[str]:
    """Generate IP addresses from network CIDR."""
    base = network.split("/")[0]
    parts = base.rsplit(".", 1)
    prefix = parts[0]
    start = int(parts[1]) if len(parts) > 1 else 0

    ips = []
    # Always include common addresses
    for special in [1, 2, 100, 200, 254]:
        ip = f"{prefix}.{special}"
        if ip not in ips:
            ips.append(ip)

    # Add sequential range
    for i in range(start + 1, min(start + count + 1, 255)):
        ip = f"{prefix}.{i}"
        if ip not in ips:
            ips.append(ip)

    return ips


def _extract_title(html: str) -> str:
    """Extract <title> from HTML."""
    import re
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return match.group(1).strip() if match else ""
