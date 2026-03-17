# src/breadmind/messenger/auto_connect/signal.py
from __future__ import annotations

import asyncio
import logging
import os
import shutil

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


class SignalAutoConnector(AutoConnector):
    platform = "signal"

    def _find_signal_cli(self) -> str | None:
        """signal-cli 바이너리 경로 탐색."""
        configured = os.environ.get("SIGNAL_CLI_PATH")
        if configured and os.path.isfile(configured):
            return configured
        return shutil.which("signal-cli")

    async def get_setup_steps(self) -> list[SetupStep]:
        phone = os.environ.get("SIGNAL_PHONE_NUMBER")
        cli_path = self._find_signal_cli()

        if phone and cli_path:
            return [
                SetupStep(
                    step_number=1,
                    title="Signal 연결 검증",
                    description="기존 Signal 설정을 검증합니다.",
                    action_type="auto",
                    auto_executable=True,
                ),
            ]

        steps = []
        step = 1

        if not cli_path:
            steps.append(
                SetupStep(
                    step_number=step,
                    title="signal-cli 설치",
                    description=(
                        "signal-cli가 설치되어 있지 않습니다.\n"
                        "아래 링크에서 설치 방법을 확인하세요.\n"
                        "- Linux: 패키지 매니저 또는 수동 설치\n"
                        "- macOS: brew install signal-cli\n"
                        "- 설치 후 다시 이 과정을 진행하세요"
                    ),
                    action_type="user_action",
                    action_url="https://github.com/AsamK/signal-cli/releases",
                ),
            )
            step += 1

        steps.append(
            SetupStep(
                step_number=step,
                title="전화번호 등록",
                description="Signal에 사용할 전화번호를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="phone_number",
                        label="전화번호",
                        placeholder="+821012345678",
                    ),
                    InputField(
                        name="signal_cli_path",
                        label="signal-cli 경로 (자동 감지되면 비워두세요)",
                        placeholder="/usr/local/bin/signal-cli",
                        required=False,
                    ),
                ],
            ),
        )
        step += 1

        steps.append(
            SetupStep(
                step_number=step,
                title="인증 코드 입력",
                description="SMS로 받은 인증 코드를 입력하세요.",
                action_type="user_input",
                input_fields=[
                    InputField(
                        name="verification_code",
                        label="인증 코드",
                        placeholder="123-456",
                    ),
                ],
            ),
        )
        step += 1

        steps.append(
            SetupStep(
                step_number=step,
                title="연결 완료",
                description="Signal 등록 및 게이트웨이 시작",
                action_type="auto",
                auto_executable=True,
            ),
        )

        return steps

    async def create_bot(self, params: dict) -> CreateResult:
        """signal-cli로 번호 등록."""
        phone = params.get("phone_number")
        cli_path = params.get("signal_cli_path") or self._find_signal_cli()

        if not cli_path:
            return CreateResult(
                success=False,
                message="signal-cli가 설치되어 있지 않습니다.",
            )

        if not phone:
            return CreateResult(success=False, message="전화번호가 필요합니다.")

        try:
            proc = await asyncio.create_subprocess_exec(
                cli_path, "-u", phone, "register",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                return CreateResult(
                    success=True,
                    message="등록 요청 완료. SMS 인증 코드를 입력하세요.",
                    credentials={"phone_number": phone, "signal_cli_path": cli_path},
                )
            return CreateResult(
                success=False,
                message="등록 실패",
                error=stderr.decode() if stderr else "unknown error",
            )
        except asyncio.TimeoutError:
            return CreateResult(success=False, message="등록 시간 초과")
        except Exception as e:
            return CreateResult(success=False, message="signal-cli 실행 실패", error=str(e))

    async def validate_credentials(self, credentials: dict) -> ValidationResult:
        phone = credentials.get("phone_number") or os.environ.get("SIGNAL_PHONE_NUMBER")
        cli_path = credentials.get("signal_cli_path") or self._find_signal_cli()

        if not phone:
            return ValidationResult(valid=False, message="전화번호가 없습니다.")
        if not cli_path:
            return ValidationResult(valid=False, message="signal-cli를 찾을 수 없습니다.")

        # signal-cli가 존재하고 번호가 등록되어 있는지 확인
        try:
            proc = await asyncio.create_subprocess_exec(
                cli_path, "-u", phone, "receive", "-t", "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return ValidationResult(
                    valid=True,
                    message=f"Signal 확인: {phone}",
                    bot_info={"phone_number": phone},
                )
            return ValidationResult(
                valid=False,
                message="Signal 번호가 등록되지 않았습니다.",
                error=stderr.decode() if stderr else None,
            )
        except asyncio.TimeoutError:
            # receive 타임아웃은 정상 (메시지가 없을 수 있음)
            return ValidationResult(
                valid=True,
                message=f"Signal 확인: {phone}",
                bot_info={"phone_number": phone},
            )
        except Exception as e:
            return ValidationResult(valid=False, message="signal-cli 오류", error=str(e))

    async def connect(self, credentials: dict) -> ConnectionResult:
        validation = await self.validate_credentials(credentials)
        if not validation.valid:
            return ConnectionResult(
                success=False, message=validation.message, error=validation.error
            )
        return ConnectionResult(
            success=True,
            message=f"Signal 연결 준비 완료: {validation.message}",
            gateway_state=GatewayState.CONFIGURED,
        )

    async def health_check(self) -> HealthStatus:
        phone = os.environ.get("SIGNAL_PHONE_NUMBER")
        if not phone:
            return HealthStatus(platform=self.platform, state=GatewayState.UNCONFIGURED)
        cli_path = self._find_signal_cli()
        if not cli_path:
            return HealthStatus(
                platform=self.platform,
                state=GatewayState.FAILED,
                error="signal-cli not found",
            )
        return HealthStatus(platform=self.platform, state=GatewayState.CONNECTED)
