"""Microsoft Teams auto-connect wizard."""
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


class TeamsAutoConnector(AutoConnector):
    platform = "teams"

    async def get_setup_steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                step_number=1,
                title="Azure Bot 등록",
                description=(
                    "Azure Portal에서 Bot 리소스를 생성하고 App ID와 Password를 받으세요.\n"
                    "https://portal.azure.com → Bot Services → Create"
                ),
                action_type="user_action",
                action_url="https://portal.azure.com/#create/Microsoft.BotServiceConnectivityGalleryPackage",
            ),
            SetupStep(
                step_number=2,
                title="Bot 자격 증명 입력",
                description="Azure에서 발급받은 App ID와 App Password를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(name="app_id", label="Microsoft App ID"),
                    InputField(name="app_password", label="App Password", secret=True),
                ],
            ),
            SetupStep(
                step_number=3,
                title="연결 확인",
                description="Bot Framework 인증을 확인합니다.",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        app_id = credentials.get("app_id", "")
        app_password = credentials.get("app_password", "")
        if not app_id or not app_password:
            return ValidationResult(
                valid=False,
                message="App ID와 Password가 필요합니다.",
            )
        try:
            url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": app_id,
                "client_secret": app_password,
                "scope": "https://api.botframework.com/.default",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, data=data, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    result = await resp.json()
                    if "access_token" in result:
                        return ValidationResult(
                            valid=True,
                            message="Bot Framework 인증 성공",
                        )
                    return ValidationResult(
                        valid=False,
                        message="Bot Framework 인증 실패",
                        error=result.get("error_description", "인증 실패"),
                    )
        except Exception as e:
            return ValidationResult(
                valid=False,
                message="Bot Framework API 연결 실패",
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
            message="Teams 봇 연결 준비 완료",
            gateway_state=GatewayState.CONFIGURED,
        )
