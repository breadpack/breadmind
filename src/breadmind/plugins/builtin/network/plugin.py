"""Network plugin — network scanning and router management."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


class NetworkPlugin(BaseToolPlugin):
    """Plugin providing network_scan and router_manage tools."""

    name = "network"
    version = "0.1.0"

    def __init__(self) -> None:
        self._vault: Any | None = None

    async def setup(self, container: Any) -> None:
        """Optionally retrieve credential_vault from the service container."""
        try:
            vault = container.get_optional("credential_vault")
            if vault is not None:
                self._vault = vault
                from breadmind.core.router_manager import get_router_manager

                get_router_manager().set_vault(vault)
                logger.info("NetworkPlugin: credential vault wired to router manager")
        except Exception as e:
            logger.debug("NetworkPlugin: credential_vault not available: %s", e)

    def get_tools(self) -> list[Callable]:
        return [network_scan, router_manage]


# ── Tool functions ────────────────────────────────────────────────────


@tool(
    description=(
        "Scan the local network to discover the router, gateway, and all "
        "connected devices. Identifies router type (ipTIME, OpenWrt, ASUS, "
        "etc.) and device types (server, NAS, PC, phone). Use when the user "
        "asks about their network, connected devices, or home server setup."
    )
)
async def network_scan() -> str:
    """Scan and report network environment."""
    from breadmind.core.network_awareness import network_scan_tool

    return await network_scan_tool()


@tool(
    description=(
        "Manage a network router via SSH/CLI. Actions: "
        "'info' — show router capabilities and setup guide, "
        "'connect' — connect to router. Call with host and router_type. "
        "If password is empty, a credential input form is automatically "
        "generated for the user to fill — just call connect even without "
        "credentials. "
        "'exec' — execute a command on connected router, "
        "'status' — show connection status, "
        "'disconnect' — disconnect from router. "
        "Supports OpenWrt, ASUS, Synology, MikroTik. "
        "WORKFLOW: To connect, call connect(host, router_type, username) "
        "with empty password — a secure input form will be returned."
    )
)
async def router_manage(
    action: str,
    router_type: str = "",
    host: str = "",
    username: str = "root",
    password: str = "",
    command: str = "",
) -> str:
    """Manage routers via SSH/CLI."""
    from breadmind.core.router_manager import get_router_manager, ROUTER_CAPABILITIES

    mgr = get_router_manager()

    if action == "info":
        if router_type:
            cap = mgr.get_capabilities(router_type)
            lines = [f"## {router_type.upper()} 라우터\n"]
            lines.append(cap.description)
            lines.append(f"\n**SSH 지원:** {'예' if cap.ssh else '아니오'}")
            lines.append(f"**웹 관리:** {'예' if cap.web_api else '아니오'}")
            if cap.setup_guide:
                lines.append(f"\n**설정 가이드:** {cap.setup_guide}")
            if cap.cli_commands:
                lines.append("\n**사용 가능한 명령어 예시:**")
                for cmd in cap.cli_commands[:8]:
                    lines.append(f"  `{cmd}`")
            return "\n".join(lines)
        else:
            lines = ["## 지원 라우터 목록\n"]
            for rtype, cap in ROUTER_CAPABILITIES.items():
                ssh = "SSH 지원" if cap.ssh else "SSH 미지원"
                lines.append(f"- **{rtype}**: {ssh} | {cap.description[:50]}...")
            return "\n".join(lines)

    elif action == "connect":
        if not host or not router_type:
            return "host와 router_type이 필요합니다."
        cap = mgr.get_capabilities(router_type)

        # Resolve credential_ref from vault if password is a reference
        actual_password = password
        actual_username = username
        logger.info(
            "router_manage connect: pw_len=%d starts_with_ref=%s pw_full=%s",
            len(password),
            password.startswith("credential_ref:"),
            repr(password),
        )
        if password.startswith("credential_ref:"):
            try:
                from breadmind.storage.credential_vault import CredentialVault

                vault = mgr._vault
                logger.info(
                    "Resolving credential_ref: %s, vault=%s",
                    password[:60],
                    vault is not None,
                )
                if vault:
                    cred_id = CredentialVault.extract_id(password)
                    raw = await vault.retrieve(cred_id)
                    logger.info(
                        "Vault retrieve for %s: found=%s", cred_id, raw is not None
                    )
                    if raw:
                        # Try JSON first (router credentials stored as JSON)
                        try:
                            data = json.loads(raw)
                            actual_password = data.get("password", raw)
                            actual_username = data.get("username", username)
                        except (ValueError, TypeError):
                            # Plain string from form submission
                            actual_password = raw
                        logger.info(
                            "Credential resolved, password length: %d",
                            len(actual_password),
                        )
            except Exception as e:
                logger.error("Credential resolution error: %s", e)

        if cap.ssh and not actual_password:
            form = {
                "id": f"ssh-{host}",
                "title": f"SSH 접속 정보 — {router_type.upper()} ({host})",
                "description": f"{cap.setup_guide}",
                "fields": [
                    {
                        "name": "host",
                        "label": "호스트",
                        "type": "text",
                        "value": host,
                        "required": True,
                    },
                    {
                        "name": "username",
                        "label": "사용자",
                        "type": "text",
                        "value": username,
                        "required": True,
                    },
                    {
                        "name": "password",
                        "label": "비밀번호",
                        "type": "password",
                        "placeholder": "SSH 비밀번호",
                        "required": True,
                    },
                ],
                "submit_message": "SSH 접속: {username}@{host}",
            }
            form_json = json.dumps(form, ensure_ascii=False)
            return (
                f"[NEED_CREDENTIALS]\n"
                f"[REQUEST_INPUT]{form_json}[/REQUEST_INPUT]"
            )
        result = await mgr.connect(host, router_type, actual_username, actual_password)
        return result["message"]

    elif action == "exec":
        if not host or not command:
            return "host와 command가 필요합니다."
        return await mgr.execute(host, command)

    elif action == "status":
        if host:
            connected = mgr.is_connected(host)
            return f"{host}: {'연결됨' if connected else '연결되지 않음'}"
        else:
            conns = mgr._connected_routers
            if not conns:
                return "연결된 라우터가 없습니다."
            lines = ["## 연결된 라우터\n"]
            for ip, cfg in conns.items():
                lines.append(
                    f"- {ip} ({cfg['type']}) — {cfg['username']}@{ip}:{cfg['port']}"
                )
            return "\n".join(lines)

    elif action == "disconnect":
        if mgr.disconnect(host):
            return f"{host} 연결 해제됨"
        return f"{host}는 연결되어 있지 않습니다."

    return (
        f"알 수 없는 action: {action}. "
        "사용 가능: info, connect, exec, status, disconnect"
    )
