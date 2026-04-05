# src/breadmind/messenger/auto_connect/gmail.py
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
    _get_base_url,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


class GmailAutoConnector(AutoConnector):
    platform = "gmail"

    def _has_existing_credentials(self) -> bool:
        return bool(os.environ.get("GMAIL_REFRESH_TOKEN"))

    def _get_verification_step(self) -> SetupStep:
        return SetupStep(
            step_number=1,
            title="Gmail 연결 검증",
            description="기존 OAuth 토큰을 검증합니다.",
            action_type="auto",
            auto_executable=True,
        )

    def _get_initial_setup_steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                step_number=1,
                title="Google Cloud 프로젝트 설정",
                description=(
                    "Google Cloud Console에서 OAuth를 설정하세요.\n"
                    "1. 아래 링크에서 새 프로젝트 생성 또는 기존 프로젝트 선택\n"
                    "2. Gmail API 활성화\n"
                    "3. OAuth 동의 화면 구성\n"
                    "4. OAuth 2.0 클라이언트 ID 생성 (웹 애플리케이션 유형)\n"
                    "5. Client ID와 Client Secret 복사"
                ),
                action_type="user_action",
                action_url="https://console.cloud.google.com/apis/credentials",
            ),
            SetupStep(
                step_number=2,
                title="OAuth 자격 증명 입력",
                description="Google Cloud Console에서 복사한 정보를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="client_id",
                        label="Client ID",
                        placeholder="xxx.apps.googleusercontent.com",
                    ),
                    InputField(
                        name="client_secret",
                        label="Client Secret",
                        placeholder="GOCSPX-...",
                        secret=True,
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="Google 계정 인증",
                description="OAuth 인증 페이지로 이동하여 Gmail 접근을 허용하세요.",
                action_type="oauth_redirect",
            ),
            SetupStep(
                step_number=4,
                title="연결 완료",
                description="OAuth 인증 완료 후 자동으로 연결됩니다.",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def get_setup_steps(self) -> list[SetupStep]:
        """Gmail은 OAuth 중간 경로가 있어 추가 분기 로직이 필요."""
        if self._has_existing_credentials():
            return [self._get_verification_step()]

        # Client ID가 있으면 바로 OAuth flow 가능
        client_id = os.environ.get("GMAIL_CLIENT_ID")
        if client_id:
            base_url = _get_base_url()
            redirect_uri = f"{base_url}/api/messenger/gmail/oauth-callback"
            oauth_url = (
                f"https://accounts.google.com/o/oauth2/v2/auth"
                f"?client_id={client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&response_type=code"
                f"&scope=https://www.googleapis.com/auth/gmail.readonly%20"
                f"https://www.googleapis.com/auth/gmail.send"
                f"&access_type=offline"
                f"&prompt=consent"
            )
            return [
                SetupStep(
                    step_number=1,
                    title="Google 계정 인증",
                    description="아래 링크를 클릭하여 Gmail 접근을 허용하세요.",
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

        return self._get_initial_setup_steps()

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        refresh_token = credentials.get("refresh_token") or os.environ.get("GMAIL_REFRESH_TOKEN")
        client_id = credentials.get("client_id") or os.environ.get("GMAIL_CLIENT_ID")
        client_secret = credentials.get("client_secret") or os.environ.get("GMAIL_CLIENT_SECRET")

        if not all([refresh_token, client_id, client_secret]):
            return ValidationResult(valid=False, message="OAuth 자격 증명이 불완전합니다.")

        try:
            async with aiohttp.ClientSession() as session:
                # refresh token으로 access token 획득
                async with session.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    token_data = await resp.json()
                    access_token = token_data.get("access_token")
                    if not access_token:
                        return ValidationResult(
                            valid=False,
                            message="토큰 갱신 실패",
                            error=token_data.get("error_description"),
                        )

                # Gmail profile 조회
                async with session.get(
                    f"{GMAIL_API}/users/me/profile",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        profile = await resp.json()
                        return ValidationResult(
                            valid=True,
                            message=f"Gmail 확인: {profile.get('emailAddress')}",
                            bot_info=profile,
                        )
                    return ValidationResult(
                        valid=False,
                        message="Gmail API 접근 실패",
                        error=f"HTTP {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Google API 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        return ConnectionResult(
            success=True,
            message=f"Gmail 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        token = os.environ.get("GMAIL_REFRESH_TOKEN")
        if not token:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
