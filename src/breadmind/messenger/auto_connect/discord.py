# src/breadmind/messenger/auto_connect/discord.py
from __future__ import annotations

import logging
import os

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    GatewayState,
    HealthStatus,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
BOT_PERMISSIONS = 274877975552  # Send Messages, Read Messages, Add Reactions, etc.


class DiscordAutoConnector(AutoConnector):
    platform = "discord"

    async def get_setup_steps(self) -> list[SetupStep]:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            return [
                SetupStep(
                    step_number=1,
                    title="토큰 검증",
                    description="기존 토큰을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        return [
            SetupStep(
                step_number=1,
                title="Discord 봇 생성",
                description=(
                    "Discord Developer Portal에서 새 애플리케이션을 만드세요.\n"
                    "1. 아래 링크에서 'New Application' 클릭\n"
                    "2. 이름 입력 (예: BreadMind)\n"
                    "3. 'Bot' 메뉴에서 'Add Bot' 클릭\n"
                    "4. 'MESSAGE CONTENT INTENT' 활성화\n"
                    "5. 'Reset Token'을 클릭하여 토큰 복사"
                ),
                action_type="user_action",
                action_url="https://discord.com/developers/applications",
            ),
            SetupStep(
                step_number=2,
                title="봇 토큰 입력",
                description="Discord Developer Portal에서 복사한 봇 토큰을 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="bot_token",
                        label="Bot Token",
                        placeholder="MTIz...",
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="서버에 봇 초대",
                description="생성된 초대 링크를 클릭하여 봇을 서버에 추가하세요.",
                action_type="user_action",
                # action_url은 토큰 검증 후 동적 생성
            ),
            SetupStep(
                step_number=4,
                title="연결 완료",
                description="토큰 검증 및 게이트웨이 시작",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        token = credentials.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            return ValidationResult(valid=False, message="Bot Token이 없습니다.")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DISCORD_API}/users/@me",
                    headers={"Authorization": f"Bot {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return ValidationResult(
                            valid=True,
                            message=f"봇 확인: {data.get('username')}#{data.get('discriminator')}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 토큰",
                        error=f"HTTP {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Discord API 오류", error=str(e))

    async def get_invite_url(self, credentials: dict) -> str | None:
        token = credentials.get("bot_token") or os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            return None
        # 봇의 application ID 조회
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{DISCORD_API}/oauth2/applications/@me",
                    headers={"Authorization": f"Bot {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        app_id = data.get("id")
                        return (
                            f"https://discord.com/oauth2/authorize"
                            f"?client_id={app_id}"
                            f"&permissions={BOT_PERMISSIONS}"
                            f"&scope=bot%20applications.commands"
                        )
        except Exception:
            pass

        client_id = os.environ.get("DISCORD_CLIENT_ID")
        if client_id:
            return (
                f"https://discord.com/oauth2/authorize"
                f"?client_id={client_id}"
                f"&permissions={BOT_PERMISSIONS}"
                f"&scope=bot%20applications.commands"
            )
        return None

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        return ConnectionResult(
            success=True,
            message=f"Discord 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({"bot_token": token})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
