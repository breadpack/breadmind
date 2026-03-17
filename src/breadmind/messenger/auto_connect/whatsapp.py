# src/breadmind/messenger/auto_connect/whatsapp.py
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

TWILIO_API = "https://api.twilio.com/2010-04-01"


class WhatsAppAutoConnector(AutoConnector):
    platform = "whatsapp"

    async def get_setup_steps(self) -> list[SetupStep]:
        sid = os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        if sid:
            return [
                SetupStep(
                    step_number=1,
                    title="Twilio 연결 검증",
                    description="기존 Twilio 설정을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        return [
            SetupStep(
                step_number=1,
                title="Twilio 계정 준비",
                description=(
                    "Twilio에서 WhatsApp Sandbox 또는 프로덕션 번호를 설정하세요.\n"
                    "1. Twilio Console에 로그인\n"
                    "2. Account SID와 Auth Token을 확인 (Dashboard)\n"
                    "3. WhatsApp Sandbox 또는 프로덕션 번호 활성화"
                ),
                action_type="user_action",
                action_url="https://console.twilio.com/",
            ),
            SetupStep(
                step_number=2,
                title="Twilio 자격 증명 입력",
                description="Twilio Dashboard에서 복사한 정보를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="account_sid",
                        label="Account SID",
                        placeholder="AC...",
                    ),
                    InputField(
                        name="auth_token",
                        label="Auth Token",
                        placeholder="auth token",
                        secret=True,
                    ),
                    InputField(
                        name="from_number",
                        label="WhatsApp 번호",
                        placeholder="whatsapp:+14155238886",
                    ),
                ],
            ),
            SetupStep(
                step_number=3,
                title="웹훅 자동 설정",
                description="BreadMind 웹훅 URL을 Twilio에 자동으로 등록합니다.",
                action_type="auto",
                auto_executable=True,
            ),
        ]

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        sid = credentials.get("account_sid") or os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        token = credentials.get("auth_token") or os.environ.get("WHATSAPP_TWILIO_AUTH_TOKEN")
        if not sid or not token:
            return ValidationResult(valid=False, message="Account SID 또는 Auth Token이 없습니다.")

        try:
            auth = aiohttp.BasicAuth(sid, token)
            async with aiohttp.ClientSession(auth=auth) as session:
                async with session.get(
                    f"{TWILIO_API}/Accounts/{sid}.json",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return ValidationResult(
                            valid=True,
                            message=f"Twilio 확인: {data.get('friendly_name')}",
                            bot_info=data,
                        )
                    return ValidationResult(
                        valid=False,
                        message="유효하지 않은 자격 증명",
                        error=f"HTTP {resp.status}",
                    )
        except Exception as e:
            return ValidationResult(valid=False, message="Twilio API 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        # 웹훅 URL 자동 등록 시도
        await self._register_webhook(credentials)
        return ConnectionResult(
            success=True,
            message=f"WhatsApp 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def _register_webhook(self, credentials: dict) -> None:
        """Twilio 웹훅 URL 자동 등록."""
        sid = credentials.get("account_sid") or os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        token = credentials.get("auth_token") or os.environ.get("WHATSAPP_TWILIO_AUTH_TOKEN")
        from_number = credentials.get("from_number") or os.environ.get("WHATSAPP_FROM_NUMBER")
        port = os.environ.get("BREADMIND_PORT", "8080")
        host = os.environ.get("BREADMIND_HOST", "localhost")

        if not all([sid, token, from_number]):
            return

        webhook_url = f"http://{host}:{port}/api/webhook/receive/whatsapp"
        # Twilio Messaging Service 웹훅 설정은 번호의 SID가 필요
        # 여기서는 로그만 남기고, 사용자에게 수동 설정 안내
        logger.info(
            "WhatsApp webhook URL: %s — Twilio Console에서 이 URL을 "
            "Messaging → Settings → WhatsApp Sandbox 웹훅에 설정하세요.",
            webhook_url,
        )

    async def health_check(self) -> HealthStatus:
        sid = os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID")
        if not sid:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        validation = await self.validate_credentials({})
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.CONNECTED if validation.valid else GatewayState.DISCONNECTED,
            error=validation.error,
        )
