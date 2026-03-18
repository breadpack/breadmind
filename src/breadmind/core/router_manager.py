"""Router management -- CLI/SSH integration for common home routers.

Provides router-specific command wrappers. Always requires user confirmation
before establishing connection. Supports OpenWrt, ASUS, Synology, MikroTik.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RouterCapability:
    """What a router can do via CLI."""

    ssh: bool = False
    web_api: bool = False
    cli_commands: list[str] = field(default_factory=list)
    description: str = ""
    setup_guide: str = ""


# Router capabilities database
ROUTER_CAPABILITIES: dict[str, RouterCapability] = {
    "openwrt": RouterCapability(
        ssh=True,
        web_api=True,
        cli_commands=[
            "uci show", "uci get", "uci set", "opkg list-installed",
            "ifconfig", "ip addr", "ip route",
            "cat /etc/config/network", "cat /etc/config/wireless",
            "cat /etc/config/firewall",
            "logread", "dmesg", "/etc/init.d/network restart",
            "free", "df -h", "uptime", "top -bn1",
        ],
        description="OpenWrt는 SSH를 통해 완전한 CLI 제어가 가능합니다. "
                    "네트워크 설정, 방화벽, 패키지 관리 등을 할 수 있습니다.",
        setup_guide="SSH가 기본 활성화되어 있습니다. "
                     "기본 계정: root / (초기 비밀번호 없음 또는 설정한 비밀번호)",
    ),
    "asus": RouterCapability(
        ssh=True,
        web_api=True,
        cli_commands=[
            "nvram show", "nvram get", "ip addr", "ip route",
            "iptables -L", "cat /proc/net/arp",
            "wl -i eth6 assoclist", "free", "df -h",
            "uptime", "ps", "logread",
        ],
        description="ASUS 라우터(특히 Merlin 펌웨어)는 SSH를 통해 CLI 제어가 가능합니다.",
        setup_guide="관리자 페이지 → 시스템 관리 → SSH 활성화 필요. 기본 포트: 22",
    ),
    "synology": RouterCapability(
        ssh=True,
        web_api=True,
        cli_commands=[
            "synoservice --status-all", "synoshare --get-all", "synonet --show",
            "cat /etc/synoinfo.conf", "df -h", "free", "uptime", "docker ps",
            "synopkg list --status", "cat /var/log/synolog/synosys.log",
        ],
        description="Synology NAS는 SSH를 통해 시스템 관리, Docker, 패키지, "
                    "스토리지를 제어할 수 있습니다.",
        setup_guide="제어판 → 터미널 및 SNMP → SSH 서비스 활성화. "
                     "admin 또는 생성한 관리자 계정 사용.",
    ),
    "mikrotik": RouterCapability(
        ssh=True,
        web_api=True,
        cli_commands=[
            "/system resource print", "/interface print",
            "/ip address print", "/ip route print",
            "/ip firewall filter print", "/system identity print",
            "/ip dhcp-server lease print", "/log print",
        ],
        description="MikroTik RouterOS는 SSH를 통해 모든 설정을 CLI로 제어할 수 있습니다.",
        setup_guide="기본 SSH 활성화. "
                     "기본 계정: admin / (비밀번호 없음 또는 설정한 비밀번호)",
    ),
    "ubiquiti": RouterCapability(
        ssh=True,
        web_api=True,
        cli_commands=[
            "mca-ctrl -t dump-sys", "ubntbox status", "ifconfig",
            "ip route", "cat /tmp/system.cfg",
            "uptime", "free", "df -h",
        ],
        description="Ubiquiti 장비는 SSH를 통해 시스템 상태 및 네트워크 설정을 "
                    "확인할 수 있습니다.",
        setup_guide="UniFi Controller 또는 장비 직접 접속. 기본 계정: ubnt / ubnt",
    ),
    "iptime": RouterCapability(
        ssh=False,
        web_api=True,
        cli_commands=[
            "browser:navigate http://192.168.0.1",
            "browser:get_text (연결된 기기 목록)",
            "browser:get_text (네트워크 설정)",
            "browser:screenshot (현재 상태)",
        ],
        description="ipTIME 라우터는 SSH를 지원하지 않지만, BreadMind의 브라우저 도구로 "
                    "웹 관리 페이지에 접속하여 설정을 확인하고 변경할 수 있습니다.",
        setup_guide="기본 주소: http://192.168.0.1 / 기본 계정: admin / admin",
    ),
    "tplink": RouterCapability(
        ssh=False,
        web_api=True,
        cli_commands=[
            "browser:navigate http://192.168.0.1",
            "browser:get_text (상태 확인)",
            "browser:screenshot (현재 상태)",
        ],
        description="TP-Link 라우터는 SSH를 지원하지 않지만, BreadMind의 브라우저 도구로 "
                    "웹 관리 페이지에 접속하여 제어할 수 있습니다.",
        setup_guide="기본 주소: http://192.168.0.1 또는 http://tplinkwifi.net",
    ),
    "netgear": RouterCapability(
        ssh=False,
        web_api=True,
        cli_commands=[
            "browser:navigate http://192.168.1.1",
            "browser:get_text (상태 확인)",
        ],
        description="Netgear 라우터는 BreadMind의 브라우저 도구로 웹 관리 페이지에 접속하여 제어합니다.",
        setup_guide="기본 주소: http://192.168.1.1 또는 http://routerlogin.net / 기본 계정: admin / password",
    ),
}


class RouterManager:
    """Manages router connections with user confirmation."""

    def __init__(self) -> None:
        self._connected_routers: dict[str, dict[str, Any]] = {}  # ip -> config

    def get_capabilities(self, router_type: str) -> RouterCapability:
        """Get capabilities for a router type."""
        return ROUTER_CAPABILITIES.get(
            router_type.lower(),
            RouterCapability(description="알 수 없는 라우터 유형입니다."),
        )

    def is_connected(self, host: str) -> bool:
        """Check if a router host is currently connected."""
        return host in self._connected_routers

    async def connect(
        self,
        host: str,
        router_type: str,
        username: str,
        password: str | None = None,
        ssh_key: str | None = None,
        port: int = 22,
    ) -> dict[str, Any]:
        """Connect to a router (after user confirmation).

        Tests the SSH connection with a safe ``echo connected`` probe.
        On success the host is added to the SSH allowed-hosts list.
        """
        cap = self.get_capabilities(router_type)
        if not cap.ssh:
            # SSH 미지원 → 브라우저로 웹 관리 페이지 접근 안내
            admin_url = f"http://{host}"
            self._connected_routers[host] = {
                "type": router_type,
                "mode": "browser",
                "admin_url": admin_url,
                "host": host,
            }
            return {
                "success": True,
                "message": (
                    f"{router_type} 라우터는 SSH를 지원하지 않지만, "
                    f"브라우저로 관리 페이지에 접속할 수 있습니다.\n"
                    f"관리자 페이지: {admin_url}\n"
                    f"{cap.setup_guide}\n\n"
                    f"'browser' 도구로 `navigate {admin_url}` 하면 "
                    f"설정을 확인하고 변경할 수 있습니다."
                ),
                "mode": "browser",
                "admin_url": admin_url,
            }

        import asyncio

        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                "-p", str(port),
                f"{username}@{host}",
                "echo", "connected",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode == 0:
                self._connected_routers[host] = {
                    "type": router_type,
                    "username": username,
                    "port": port,
                    "host": host,
                }

                # Add to SSH allowed hosts so shell_exec can reach it
                from breadmind.tools.builtin import ToolSecurityConfig

                current = ToolSecurityConfig.get_config()
                allowed: list[str] = current.get("allowed_ssh_hosts", [])
                if host not in allowed:
                    allowed.append(host)
                    ToolSecurityConfig.update(allowed_ssh_hosts=allowed)

                return {
                    "success": True,
                    "message": f"{router_type} 라우터({host}) 연결 성공!",
                }
            else:
                error = stderr.decode(errors="ignore").strip()
                return {"success": False, "message": f"SSH 연결 실패: {error}"}

        except asyncio.TimeoutError:
            return {"success": False, "message": "SSH 연결 시간 초과 (10초)"}
        except Exception as e:
            return {"success": False, "message": f"연결 오류: {e}"}

    async def execute(self, host: str, command: str) -> str:
        """Execute a command on a connected router (SSH or browser)."""
        config = self._connected_routers.get(host)
        if not config:
            return f"[error] {host}에 연결되지 않았습니다. 먼저 연결하세요."

        # Browser mode — delegate to browser tool
        if config.get("mode") == "browser":
            admin_url = config.get("admin_url", f"http://{host}")
            return (
                f"[browser_mode] 이 라우터는 브라우저로 제어합니다.\n"
                f"'browser' 도구를 사용하세요:\n"
                f"  action=navigate, url={admin_url}\n"
                f"  action=get_text (페이지 내용 읽기)\n"
                f"  action=click, selector=... (버튼 클릭)\n"
                f"  action=screenshot (화면 캡처)"
            )

        import asyncio

        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                "-p", str(config.get('port', 22)),
                f"{config.get('username', 'root')}@{host}",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode(errors="ignore")
            if stderr:
                output += "\n" + stderr.decode(errors="ignore")
            return output.strip()
        except asyncio.TimeoutError:
            return "[error] 명령 실행 시간 초과"
        except Exception as e:
            return f"[error] {e}"

    def disconnect(self, host: str) -> bool:
        """Disconnect from a router. Returns True if it was connected."""
        return self._connected_routers.pop(host, None) is not None


# Singleton
_manager = RouterManager()


def get_router_manager() -> RouterManager:
    """Return the singleton RouterManager instance."""
    return _manager
