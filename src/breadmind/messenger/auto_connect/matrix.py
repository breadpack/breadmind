"""Matrix auto-connect wizard."""
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


class MatrixAutoConnector(AutoConnector):
    platform = "matrix"

    def _get_initial_setup_steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                step_number=1,
                title="Matrix 계정 준비",
                description=(
                    "Matrix 홈서버 주소와 액세스 토큰을 준비하세요.\n"
                    "Element 등 Matrix 클라이언트에서 설정 → 도움말 → 고급에서 확인 가능합니다."
                ),
                action_type="user_action",
            ),
            SetupStep(
                step_number=2,
                title="Matrix 서버 정보 입력",
                description="홈서버 URL과 액세스 토큰을 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="homeserver",
                        label="Homeserver URL",
                        placeholder="https://matrix.org",
                    ),
                    InputField(
                        name="access_token",
                        label="Access Token",
                        secret=True,
                    ),
                    InputField(
                        name="user_id",
                        label="User ID",
                        required=False,
                        placeholder="@bot:matrix.org",
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="연결 확인",
                description="Matrix 서버 연결을 확인합니다.",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        homeserver = credentials.get("homeserver", "").rstrip("/")
        token = credentials.get("access_token", "")
        if not homeserver or not token:
            return ValidationResult(
                valid=False,
                message="Homeserver URL과 Access Token이 필요합니다.",
            )
        try:
            url = f"{homeserver}/_matrix/client/v3/account/whoami"
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        user_id = data.get("user_id", "Matrix User")
                        return ValidationResult(
                            valid=True,
                            message=f"인증 확인: {user_id}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="Matrix 인증 실패",
                        error=f"인증 실패: {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(
                valid=False,
                message="Matrix 서버 연결 실패",
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
            message=f"Matrix 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )
