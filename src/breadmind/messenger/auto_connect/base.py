from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class GatewayState(str, Enum):
    UNCONFIGURED = "unconfigured"
    CONFIGURED = "configured"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class InputField:
    name: str
    label: str
    placeholder: str = ""
    secret: bool = False
    required: bool = True


@dataclass
class SetupStep:
    step_number: int
    title: str
    description: str
    action_type: str  # "auto" | "user_input" | "user_action" | "oauth_redirect"
    action_url: str | None = None
    input_fields: list[InputField] | None = None
    auto_executable: bool = False


@dataclass
class CreateResult:
    success: bool
    message: str
    credentials: dict[str, str] | None = None
    error: str | None = None


@dataclass
class ValidationResult:
    valid: bool
    message: str
    bot_info: dict | None = None
    error: str | None = None


@dataclass
class ConnectionResult:
    success: bool
    message: str
    gateway_state: GatewayState = GatewayState.DISCONNECTED
    error: str | None = None


@dataclass
class HealthStatus:
    platform: str
    state: GatewayState
    last_check: str | None = None
    last_message: str | None = None
    error: str | None = None
    retry_count: int = 0
    uptime_seconds: float = 0.0


@dataclass
class WizardState:
    session_id: str
    platform: str
    current_step: int
    total_steps: int
    step_info: SetupStep | None
    status: str  # "waiting_input" | "processing" | "completed" | "failed"
    message: str
    error: str | None = None
    credentials: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def new(platform: str, total_steps: int, first_step: SetupStep) -> WizardState:
        return WizardState(
            session_id=str(uuid.uuid4()),
            platform=platform,
            current_step=1,
            total_steps=total_steps,
            step_info=first_step,
            status="waiting_input",
            message=first_step.description,
        )


class AutoConnector(ABC):
    """플랫폼별 자동 연결 로직의 기본 클래스."""

    platform: str = ""

    @abstractmethod
    async def get_setup_steps(self) -> list[SetupStep]:
        """연결에 필요한 단계 목록을 반환."""

    async def create_bot(self, params: dict) -> CreateResult:
        """봇/앱 자동 생성 (지원하는 플랫폼만 구현)."""
        return CreateResult(
            success=False,
            message=f"{self.platform}은 봇 자동 생성을 지원하지 않습니다.",
        )

    @abstractmethod
    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        """자격 증명 검증."""

    @abstractmethod
    async def connect(self, credentials: dict) -> ConnectionResult:
        """게이트웨이 연결 시작."""

    async def health_check(self) -> HealthStatus:
        """연결 상태 확인."""
        return HealthStatus(
            platform=self.platform,
            state=GatewayState.UNCONFIGURED,
        )

    async def get_invite_url(self, credentials: dict) -> str | None:
        """서버/채널 초대 URL 생성 (지원하는 플랫폼만)."""
        return None
