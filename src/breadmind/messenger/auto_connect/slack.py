# src/breadmind/messenger/auto_connect/slack.py
from __future__ import annotations

import logging
import os

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    CreateResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)

SLACK_APP_MANIFEST = {
    "display_information": {
        "name": "BreadMind",
        "description": "AI Infrastructure Agent",
        "background_color": "#2c2d30",
    },
    "features": {
        "bot_user": {"display_name": "BreadMind", "always_online": True},
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "chat:write",
                "channels:history",
                "channels:read",
                "groups:history",
                "groups:read",
                "im:history",
                "im:read",
                "im:write",
                "mpim:history",
                "mpim:read",
                "app_mentions:read",
                "reactions:read",
                "reactions:write",
            ],
        },
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": ["message.im", "app_mention"],
        },
        "socket_mode_enabled": True,
        "org_deploy_enabled": False,
    },
}


class SlackAutoConnector(AutoConnector):
    platform = "slack"

    async def get_setup_steps(self) -> list[SetupStep]:
        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        app_token = os.environ.get("SLACK_APP_TOKEN")

        if bot_token and app_token:
            return [
                SetupStep(
                    step_number=1,
                    title="토큰 검증",
                    description="기존 토큰을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        client_id = os.environ.get("SLACK_CLIENT_ID")
        if client_id:
            # OAuth flow 가능
            port = os.environ.get("BREADMIND_PORT", "8080")
            redirect_uri = f"http://localhost:{port}/api/messenger/slack/oauth-callback"
            oauth_url = (
                f"https://slack.com/oauth/v2/authorize"
                f"?client_id={client_id}"
                f"&scope=chat:write,channels:history,channels:read,im:history,im:read,im:write,app_mentions:read"
                f"&redirect_uri={redirect_uri}"
            )
            return [
                SetupStep(
                    step_number=1,
                    title="Slack 앱 승인",
                    description="아래 링크를 클릭하여 BreadMind 앱을 워크스페이스에 설치하세요.",
                    action_type="oauth_redirect",
                    action_url=oauth_url,
                ),
                SetupStep(
                    step_number=2,
                    title="연결 완료",
                    description="OAuth 인증이 완료되면 자동으로 연결됩니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        # 수동 설정
        return [
            SetupStep(
                step_number=1,
                title="Slack 앱 생성",
                description=(
                    "Slack API 사이트에서 새 앱을 만드세요.\n"
                    "1. 아래 링크에서 'Create New App' → 'From a manifest' 선택\n"
                    "2. 워크스페이스를 선택하세요\n"
                    "3. BreadMind가 제공하는 매니페스트를 붙여넣으세요"
                ),
                action_type="user_action",
                action_url="https://api.slack.com/apps",
            ),
            SetupStep(
                step_number=2,
                title="토큰 입력",
                description=(
                    "앱 설정에서 Bot Token과 App-Level Token을 복사하세요.\n"
                    "- Bot Token: OAuth & Permissions → Bot User OAuth Token (xoxb-...)\n"
                    "- App Token: Basic Information → App-Level Tokens (xapp-...)"
                ),
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="bot_token",
                        label="Bot Token",
                        placeholder="xoxb-...",
                        secret=True,
                    ),
                    InputField(
                        name="app_token",
                        label="App-Level Token",
                        placeholder="xapp-...",
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="연결 완료",
                description="토큰 검증 및 게이트웨이 시작",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def create_bot(self, params: dict) -> CreateResult:
        """Slack App Manifest API로 앱 생성 시도."""
        config_token = params.get("config_token")
        if not config_token:
            return CreateResult(
                success=False,
                message="Configuration token이 필요합니다. Slack API에서 수동으로 앱을 생성하세요.",
            )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/apps.manifest.create",
                    json={"manifest": SLACK_APP_MANIFEST},
                    headers={"Authorization": f"Bearer {config_token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        creds = data.get("credentials", {})
                        return CreateResult(
                            success=True,
                            message="Slack 앱이 생성되었습니다.",
                            credentials={
                                "client_id": creds.get("client_id", ""),
                                "client_secret": creds.get("client_secret", ""),
                                "app_id": data.get("app_id", ""),
                            },
                        )
                    return CreateResult(
                        success=False,
                        message="앱 생성 실패",
                        error=data.get("error"),
                    )
        except Exception as e:
            return CreateResult(success=False, message="Slack API 오류", error=str(e))

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        bot_token = credentials.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            return ValidationResult(valid=False, message="Bot Token이 없습니다.")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        return ValidationResult(
                            valid=True,
                            message=f"연결 확인: {data.get('team')} / {data.get('user')}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 토큰",
                        error=data.get("error"),
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Slack API 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False,
                message=validation.message,
                error=validation.error,
            )
        return ConnectionResult(
            success=True,
            message=f"Slack 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({"bot_token": token})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
