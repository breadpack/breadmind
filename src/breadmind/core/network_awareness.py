"""Network environment awareness — detects router, gateway, and connected devices.

Works on Windows, macOS, and Linux. No configuration needed.
Supports ipTIME, OpenWrt, and generic routers.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import socket
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class NetworkDevice:
    """A device discovered on the local network."""
    ip: str
    mac: str = ""
    hostname: str = ""
    vendor: str = ""
    device_type: str = "unknown"  # router, server, nas, phone, pc, iot, unknown
    is_gateway: bool = False


@dataclass
class RouterInfo:
    """Information about the network router/gateway."""
    ip: str
    type: str = "unknown"  # iptime, openwrt, asus, tplink, generic
    model: str = ""
    firmware: str = ""
    admin_url: str = ""


@dataclass
class NetworkEnvironment:
    """Complete network environment snapshot."""
    local_ip: str = ""
    gateway_ip: str = ""
    subnet: str = ""
    router: RouterInfo | None = None
    devices: list[NetworkDevice] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=list)


async def detect_environment() -> NetworkEnvironment:
    """Detect the full network environment. No configuration needed."""
    env = NetworkEnvironment()

    # Step 1: Get local IP and gateway
    env.local_ip = _get_local_ip()
    env.gateway_ip = await _get_gateway()
    env.subnet = _ip_to_subnet(env.local_ip)
    env.dns_servers = _get_dns_servers()

    logger.info("Network: local=%s, gateway=%s, subnet=%s", env.local_ip, env.gateway_ip, env.subnet)

    # Step 2: Identify router
    if env.gateway_ip:
        env.router = await identify_router(env.gateway_ip)

    # Step 3: Get connected devices
    env.devices = await discover_devices(env.gateway_ip, env.router)

    return env


def _get_local_ip() -> str:
    """Get the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


async def _get_gateway() -> str:
    """Get the default gateway IP."""
    system = platform.system()
    try:
        if system == "Windows":
            proc = await asyncio.create_subprocess_exec(
                "cmd", "/c", "ipconfig",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text = stdout.decode("cp949", errors="ignore")
            # Find "Default Gateway" or "기본 게이트웨이"
            for line in text.splitlines():
                if "gateway" in line.lower() or "게이트웨이" in line:
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                    if match:
                        return match.group(1)
        else:
            proc = await asyncio.create_subprocess_exec(
                "ip", "route", "show", "default",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text = stdout.decode()
            match = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", text)
            if match:
                return match.group(1)
            # macOS fallback
            proc = await asyncio.create_subprocess_exec(
                "netstat", "-rn",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text = stdout.decode()
            for line in text.splitlines():
                if line.startswith("default") or line.startswith("0.0.0.0"):
                    parts = line.split()
                    if len(parts) >= 2:
                        gw = parts[1]
                        if re.match(r"\d+\.\d+\.\d+\.\d+", gw):
                            return gw
    except Exception:
        pass

    # Common defaults
    local_ip = _get_local_ip()
    prefix = local_ip.rsplit(".", 1)[0]
    return f"{prefix}.1"


def _get_dns_servers() -> list[str]:
    """Get DNS server addresses."""
    servers: list[str] = []
    system = platform.system()

    try:
        if system == "Windows":
            import subprocess
            result = subprocess.run(
                ["cmd", "/c", "ipconfig", "/all"],
                capture_output=True, timeout=5,
            )
            text = result.stdout.decode("cp949", errors="ignore")
            in_dns = False
            for line in text.splitlines():
                if "dns" in line.lower() and "server" in line.lower():
                    in_dns = True
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                    if match:
                        servers.append(match.group(1))
                elif in_dns and line.strip() and ":" not in line.split(".", 1)[0]:
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                    if match:
                        servers.append(match.group(1))
                    else:
                        in_dns = False
                else:
                    in_dns = False
        else:
            try:
                with open("/etc/resolv.conf") as f:
                    for line in f:
                        if line.strip().startswith("nameserver"):
                            parts = line.split()
                            if len(parts) >= 2:
                                servers.append(parts[1])
            except FileNotFoundError:
                pass
    except Exception:
        pass

    return servers


async def identify_router(gateway_ip: str) -> RouterInfo:
    """Identify the router type by checking its admin page."""
    info = RouterInfo(ip=gateway_ip)

    # Try HTTP first, then HTTPS
    for scheme in ("http", "https"):
        url = f"{scheme}://{gateway_ip}/"
        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout, ssl=False, allow_redirects=True) as resp:
                    text = await resp.text()
                    dict(resp.headers)
                    final_url = str(resp.url)

                    info.admin_url = final_url

                    # ipTIME detection
                    if any(kw in text.lower() for kw in ["iptime", "efm", "timepro"]):
                        info.type = "iptime"
                        info.model = _extract_iptime_model(text)
                        info.admin_url = url
                        logger.info("Router identified: ipTIME %s at %s", info.model, gateway_ip)
                        return info

                    # OpenWrt detection
                    if any(kw in text.lower() for kw in ["openwrt", "luci", "lede"]):
                        info.type = "openwrt"
                        info.admin_url = url
                        logger.info("Router identified: OpenWrt at %s", gateway_ip)
                        return info

                    # ASUS detection
                    if "asus" in text.lower() or "asuswrt" in text.lower():
                        info.type = "asus"
                        info.admin_url = url
                        return info

                    # TP-Link detection
                    if "tp-link" in text.lower() or "tplink" in text.lower():
                        info.type = "tplink"
                        info.admin_url = url
                        return info

                    # Netgear detection
                    if "netgear" in text.lower():
                        info.type = "netgear"
                        info.admin_url = url
                        return info

                    # Generic router with web UI
                    if "router" in text.lower() or "login" in text.lower():
                        info.type = "generic"
                        info.admin_url = url
                        return info

        except Exception:
            continue

    info.type = "unknown"
    return info


async def discover_devices(gateway_ip: str, router: RouterInfo | None = None) -> list[NetworkDevice]:
    """Discover connected devices using ARP table and optionally router admin."""
    devices = []

    # Method 1: ARP table (always available, no auth needed)
    arp_devices = await _get_arp_devices()
    devices.extend(arp_devices)

    # Method 2: Ping sweep to populate ARP table (quick, just a few IPs)
    subnet = _ip_to_subnet(gateway_ip)
    await _ping_sweep(subnet, count=10)
    # Re-read ARP after ping sweep
    arp_after = await _get_arp_devices()
    for dev in arp_after:
        if not any(d.ip == dev.ip for d in devices):
            devices.append(dev)

    # Mark the gateway
    for dev in devices:
        if dev.ip == gateway_ip:
            dev.is_gateway = True
            dev.device_type = "router"
            if router:
                dev.hostname = f"{router.type} router"

    # Try to resolve hostnames
    for dev in devices:
        if not dev.hostname:
            dev.hostname = await _resolve_hostname(dev.ip)

    # Guess device types from MAC vendor (basic heuristic)
    for dev in devices:
        if dev.device_type == "unknown":
            dev.device_type = _guess_device_type(dev)

    return devices


async def _get_arp_devices() -> list[NetworkDevice]:
    """Read ARP table for discovered devices."""
    devices = []
    system = platform.system()

    try:
        if system == "Windows":
            proc = await asyncio.create_subprocess_exec(
                "cmd", "/c", "arp", "-a",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text = stdout.decode("cp949", errors="ignore")
            for line in text.splitlines():
                match = re.search(
                    r"(\d+\.\d+\.\d+\.\d+)\s+"
                    r"([\da-f]{2}[:-][\da-f]{2}[:-][\da-f]{2}[:-]"
                    r"[\da-f]{2}[:-][\da-f]{2}[:-][\da-f]{2})",
                    line, re.I,
                )
                if match:
                    ip = match.group(1)
                    mac = match.group(2).replace("-", ":").lower()
                    if mac != "ff:ff:ff:ff:ff:ff" and not ip.endswith(".255"):
                        devices.append(NetworkDevice(ip=ip, mac=mac))
        else:
            proc = await asyncio.create_subprocess_exec(
                "arp", "-a",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text = stdout.decode()
            for line in text.splitlines():
                match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([\da-f:]{17})", line, re.I)
                if match:
                    devices.append(NetworkDevice(ip=match.group(1), mac=match.group(2).lower()))
                else:
                    # Linux format: IP HWtype HWaddress
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+([\da-f:]{17})", line, re.I)
                    if match:
                        devices.append(NetworkDevice(ip=match.group(1), mac=match.group(2).lower()))
    except Exception:
        pass

    return devices


async def _ping_sweep(subnet: str, count: int = 10) -> None:
    """Quick ping sweep to populate ARP table."""
    prefix = subnet.rsplit(".", 1)[0]
    system = platform.system()
    ping_flag = "-n" if system == "Windows" else "-c"

    tasks = []
    # Ping common IPs
    targets = [1, 2, 3, 10, 20, 50, 100, 150, 200, 254][:count]
    for i in targets:
        ip = f"{prefix}.{i}"
        tasks.append(_ping_one(ip, ping_flag))

    await asyncio.gather(*tasks)


async def _ping_one(ip: str, flag: str) -> None:
    """Ping a single IP (just to populate ARP table)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", flag, "1", "-w", "500" if platform.system() == "Windows" else "1", ip,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=2)
    except Exception:
        pass


async def _resolve_hostname(ip: str) -> str:
    """Try to resolve hostname via reverse DNS."""
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: socket.gethostbyaddr(ip)
        )
        return result[0]
    except Exception:
        return ""


def _ip_to_subnet(ip: str) -> str:
    """Convert an IP address to its /24 subnet base (e.g. 192.168.0.15 -> 192.168.0.0)."""
    parts = ip.rsplit(".", 1)
    return f"{parts[0]}.0"


def _extract_iptime_model(html: str) -> str:
    """Extract ipTIME model from admin page HTML."""
    match = re.search(r"(A\d{4}|N\d{3,4}|AX\d{4}|T\d{4})", html, re.I)
    return match.group(1) if match else "unknown"


def _guess_device_type(dev: NetworkDevice) -> str:
    """Guess device type from MAC prefix and hostname."""
    mac_prefix = dev.mac[:8] if dev.mac else ""
    hostname_lower = dev.hostname.lower()

    # Synology
    if "synology" in hostname_lower or "diskstation" in hostname_lower:
        return "nas"
    if mac_prefix.startswith("00:11:32"):  # Synology MAC prefix
        return "nas"

    # Known server indicators
    if any(kw in hostname_lower for kw in ["proxmox", "pve", "server", "srv", "node"]):
        return "server"

    # Known PC indicators
    if any(kw in hostname_lower for kw in ["desktop", "laptop", "pc", "windows", "mac"]):
        return "pc"

    # Known phone/mobile
    if any(kw in hostname_lower for kw in ["iphone", "galaxy", "android", "phone", "pixel"]):
        return "phone"

    # IoT
    if any(kw in hostname_lower for kw in ["esp", "arduino", "iot", "sensor", "camera", "cam"]):
        return "iot"

    return "unknown"


# --- LLM Tool wrapper ---

async def network_scan_tool() -> str:
    """Scan and report network environment (for LLM tool use)."""
    env = await detect_environment()

    lines = ["## 네트워크 환경\n"]
    lines.append(f"- 내 IP: {env.local_ip}")
    lines.append(f"- 게이트웨이: {env.gateway_ip}")
    lines.append(f"- 서브넷: {env.subnet}")

    if env.router:
        router_type = {
            "iptime": "ipTIME", "openwrt": "OpenWrt",
            "asus": "ASUS", "tplink": "TP-Link",
        }.get(env.router.type, env.router.type)
        lines.append(f"- 라우터: {router_type} {env.router.model}")
        if env.router.admin_url:
            lines.append(f"- 관리자 페이지: {env.router.admin_url}")

    if env.devices:
        lines.append(f"\n## 연결된 기기 ({len(env.devices)}대)\n")
        type_icons = {
            "router": "[router]", "server": "[server]", "nas": "[nas]",
            "pc": "[pc]", "phone": "[phone]", "iot": "[iot]", "unknown": "[?]",
        }
        for dev in sorted(env.devices, key=lambda d: tuple(int(p) for p in d.ip.split("."))):
            icon = type_icons.get(dev.device_type, "[?]")
            name = dev.hostname or dev.ip
            mac_str = f" ({dev.mac})" if dev.mac else ""
            gw_str = " <- router" if dev.is_gateway else ""
            lines.append(f"  {icon} {dev.ip} -- {name}{mac_str}{gw_str}")

    return "\n".join(lines)
