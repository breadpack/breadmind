# src/breadmind/messenger/auto_connect/telegram.py
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

TELEGRAM_API = "https://api.telegram.org"


class TelegramAutoConnector(AutoConnector):
    platform = "telegram"

    async def get_setup_steps(self) -> list[SetupStep]:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
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
                title="BotFather에서 봇 생성",
                description=(
                    "Telegram에서 @BotFather와 대화하여 봇을 만드세요.\n"
                    "1. 아래 링크를 클릭하세요\n"
                    "2. /newbot 명령을 보내세요\n"
                    "3. 봇 이름과 유저네임을 설정하세요\n"
                    "4. 받은 토큰을 복사하세요"
                ),
                action_type="user_action",
                action_url="https://t.me/BotFather?start=start",
            ),
            SetupStep(
                step_number=2,
                title="봇 토큰 입력",
                description="BotFather에서 받은 봇 토큰을 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="bot_token",
                        label="Bot Token",
                        placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
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

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        token = credentials.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return ValidationResult(valid=False, message="토큰이 없습니다.")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{TELEGRAM_API}/bot{token}/getMe", timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        bot = data["result"]
                        return ValidationResult(
                            valid=True,
                            message=f"봇 확인: @{bot.get('username')} ({bot.get('first_name')})",
                            bot_info=bot,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 토큰입니다.",
                        error=data.get("description"),
                    )
        except Exception as e:
            return ValidationResult(
                valid=False,
                message="Telegram API 연결 실패",
                error=str(e),
            )

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
            message=f"Telegram 봇 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)

        validation = await self.validate_credentials({"bot_token": token})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
