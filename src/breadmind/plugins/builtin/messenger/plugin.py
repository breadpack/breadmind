"""Messenger platform connection tool plugin."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


class MessengerPlugin(BaseToolPlugin):
    """Plugin providing the messenger_connect tool."""

    name = "messenger"
    version = "0.1.0"

    def __init__(self) -> None:
        self._orchestrator: Any | None = None
        self._tools: list[Callable] = []

    async def setup(self, container: Any) -> None:
        self._orchestrator = container.get_optional("connection_orchestrator")
        self._tools = self._build_tools()

    def _build_tools(self) -> list[Callable]:
        orchestrator = self._orchestrator

        @tool(
            description=(
                "Connect a messenger platform (slack, discord, telegram, whatsapp, gmail, signal). "
                "Returns a URL that the user's browser will automatically open for OAuth authorization. "
                "Use when user asks to connect/integrate a messenger."
            )
        )
        async def messenger_connect(platform: str) -> str:
            """Generate connection URL for a messenger platform."""
            from breadmind.messenger.auto_connect.base import _get_base_url

            platform_lower = platform.lower().strip()
            valid = {"slack", "discord", "telegram", "whatsapp", "gmail", "signal"}
            if platform_lower not in valid:
                return f"Invalid platform '{platform_lower}'. Choose from: {', '.join(valid)}"

            # Try orchestrator-based auto-connect first
            if orchestrator is not None:
                try:
                    state = await orchestrator.start_connection(platform_lower, "chat")
                    if state.status == "failed":
                        logger.warning(
                            "Orchestrator failed for %s, falling back to legacy: %s",
                            platform_lower, state.error,
                        )
                    else:
                        msg = state.message or f"{platform_lower} 연결 위자드가 시작되었습니다."
                        if state.step_info and state.step_info.action_url:
                            msg += f"\n[OPEN_URL]{state.step_info.action_url}[/OPEN_URL]"
                        msg += f"\n(세션 ID: {state.session_id})"
                        return msg
                except Exception as e:
                    logger.warning(
                        "Orchestrator error for %s, falling back to legacy: %s",
                        platform_lower, e,
                    )

            # Legacy behavior (fallback)
            if platform_lower == "whatsapp":
                sid = os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID", "")
                if sid:
                    return (
                        "WhatsApp (Twilio)이 설정되어 있습니다. "
                        "Settings 페이지에서 Webhook URL을 Twilio 콘솔에 등록해주세요."
                    )
                else:
                    return (
                        "[OPEN_URL]https://console.twilio.com/[/OPEN_URL] "
                        "Twilio 콘솔을 열었습니다. WhatsApp Sandbox를 설정하고 "
                        "Account SID, Auth Token을 Settings 페이지에서 입력해주세요."
                    )

            elif platform_lower == "gmail":
                client_id = os.environ.get("GMAIL_CLIENT_ID", "")
                if client_id:
                    base_url = _get_base_url()
                    redirect_uri = f"{base_url}/api/messenger/gmail/oauth-callback"
                    scopes = "https://www.googleapis.com/auth/gmail.modify"
                    url = (
                        f"https://accounts.google.com/o/oauth2/v2/auth?"
                        f"client_id={client_id}&redirect_uri={redirect_uri}"
                        f"&response_type=code&scope={scopes}"
                        f"&access_type=offline&prompt=consent"
                    )
                    return (
                        f"[OPEN_URL]{url}[/OPEN_URL] "
                        "Gmail OAuth 페이지를 열었습니다. Google 계정 접근을 허용해주세요."
                    )
                else:
                    return (
                        "[OPEN_URL]https://console.cloud.google.com/apis/credentials[/OPEN_URL] "
                        "Google Cloud Console을 열었습니다. OAuth 2.0 Client ID를 만들고 "
                        "Client ID, Client Secret을 Settings 페이지에서 입력해주세요."
                    )

            elif platform_lower == "signal":
                return (
                    "Signal은 signal-cli를 사용합니다. signal-cli를 설치하고 "
                    "(https://github.com/AsamK/signal-cli) 전화번호를 등록한 후, "
                    "Settings 페이지에서 전화번호를 입력해주세요."
                )

            elif platform_lower == "slack":
                client_id = os.environ.get("SLACK_CLIENT_ID", "")
                if client_id:
                    base_url = _get_base_url()
                    redirect_uri = f"{base_url}/api/messenger/slack/oauth-callback"
                    scopes = "chat:write,app_mentions:read,channels:read,im:read,im:write,im:history"
                    url = (
                        f"https://slack.com/oauth/v2/authorize?"
                        f"client_id={client_id}&scope={scopes}&redirect_uri={redirect_uri}"
                    )
                    return (
                        f"[OPEN_URL]{url}[/OPEN_URL] "
                        "Slack OAuth 페이지를 열었습니다. 브라우저에서 워크스페이스 접근을 허용해주세요."
                    )
                else:
                    return (
                        "[OPEN_URL]https://api.slack.com/apps[/OPEN_URL] "
                        "Slack App이 아직 설정되지 않았습니다. 브라우저에서 Slack API 페이지를 열었습니다. "
                        "새 앱을 만들고 Bot Token(xoxb-...)과 App Token(xapp-...)을 "
                        "Settings 페이지에서 입력해주세요."
                    )

            elif platform_lower == "discord":
                client_id = os.environ.get("DISCORD_CLIENT_ID", "")
                if client_id:
                    permissions = 274877975552
                    url = (
                        f"https://discord.com/oauth2/authorize?"
                        f"client_id={client_id}&permissions={permissions}&scope=bot"
                    )
                    return (
                        f"[OPEN_URL]{url}[/OPEN_URL] "
                        "Discord 봇 초대 페이지를 열었습니다. 서버를 선택하고 인증해주세요."
                    )
                else:
                    return (
                        "[OPEN_URL]https://discord.com/developers/applications[/OPEN_URL] "
                        "Discord Application이 아직 설정되지 않았습니다. "
                        "브라우저에서 Developer Portal을 열었습니다. "
                        "새 Application을 만들고 Bot Token을 Settings 페이지에서 입력해주세요."
                    )

            elif platform_lower == "telegram":
                return (
                    "[OPEN_URL]https://t.me/BotFather[/OPEN_URL] "
                    "Telegram BotFather를 열었습니다. /newbot 명령으로 봇을 만들고, "
                    "발급된 토큰을 Settings 페이지의 Telegram Bot Token 필드에 입력해주세요."
                )

        return [messenger_connect]

    def get_tools(self) -> list[Callable]:
        return self._tools
