"""LINE auto-connect wizard."""
from __future__ import annotations

import logging

import aiohttp

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    ConnectionResult,
    GatewayState,
    InputField,
    SetupStep,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class LINEAutoConnector(AutoConnector):
    platform = "line"

    def _get_initial_setup_steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                step_number=1,
                title="LINE Developers 채널 생성",
                description=(
                    "LINE Developers Console에서 Messaging API 채널을 생성하세요.\n"
                    "https://developers.line.biz/console/"
                ),
                action_type="user_action",
                action_url="https://developers.line.biz/console/",
            ),
            SetupStep(
                step_number=2,
                title="채널 토큰 입력",
                description="Channel Access Token을 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="channel_token",
                        label="Channel Access Token",
                        secret=True,
                    ),
                    InputField(
                        name="channel_secret",
                        label="Channel Secret",
                        required=False,
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="연결 확인",
                description="LINE API 연결을 확인합니다.",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        token = credentials.get("channel_token", "")
        if not token:
            return ValidationResult(
                valid=False,
                message="Channel Access Token이 필요합니다.",
            )
        try:
            url = "https://api.line.me/v2/bot/info"
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        display_name = data.get("displayName", "LINE Bot")
                        return ValidationResult(
                            valid=True,
                            message=f"봇 확인: {display_name}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 토큰입니다.",
                        error=f"API 응답: {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(
                valid=False,
                message="LINE API 연결 실패",
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
            message=f"LINE 봇 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )
