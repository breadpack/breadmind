# src/breadmind/messenger/auto_connect/orchestrator.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from breadmind.messenger.auto_connect.base import (
    AutoConnector,
    GatewayState,
    SetupStep,
    WizardState,
)
from breadmind.messenger.platforms import (
    create_connector,
    get_all_platforms,
    get_field_to_env_map,
)

logger = logging.getLogger(__name__)

SESSION_TTL = 1800  # 30 minutes


@dataclass
class _Session:
    wizard: WizardState
    connector: AutoConnector
    steps: list[SetupStep]
    created_at: float


class ConnectionOrchestrator:
    """3개 인터페이스(웹/채팅/CLI)의 연결 요청을 통합 처리하는 위자드 상태 머신."""

    def __init__(self, security_manager, lifecycle_manager, db):
        self._sessions: dict[str, _Session] = {}
        self._security = security_manager
        self._lifecycle = lifecycle_manager
        self._db = db
        self._connectors: dict[str, AutoConnector] = {}
        self._register_connectors()

    def _register_connectors(self) -> None:
        for name in get_all_platforms():
            try:
                connector = create_connector(name)
                if connector:
                    self._connectors[connector.platform] = connector
            except (ImportError, AttributeError) as e:
                logger.warning("Cannot load connector for %s: %s", name, e)

    async def start_connection(
        self, platform: str, interface: str = "web"
    ) -> WizardState:
        """연결 위자드 시작. 같은 플랫폼에 기존 세션이 있으면 이어서 진행."""
        self._cleanup_expired()

        # 기존 세션 확인
        for session in self._sessions.values():
            if (
                session.wizard.platform == platform
                and session.wizard.status not in ("completed", "failed")
            ):
                return session.wizard

        connector = self._connectors.get(platform)
        if not connector:
            return WizardState(
                session_id="",
                platform=platform,
                current_step=0,
                total_steps=0,
                step_info=None,
                status="failed",
                message=f"지원하지 않는 플랫폼: {platform}",
                error="unsupported_platform",
            )

        steps = await connector.get_setup_steps()
        wizard = WizardState.new(platform, len(steps), steps[0])

        self._sessions[wizard.session_id] = _Session(
            wizard=wizard,
            connector=connector,
            steps=steps,
            created_at=time.time(),
        )

        logger.info(
            "Connection wizard started: %s (session=%s, interface=%s, steps=%d)",
            platform,
            wizard.session_id,
            interface,
            len(steps),
        )

        # auto_executable 단계면 자동 실행
        if steps[0].auto_executable:
            return await self._execute_auto_step(wizard.session_id)

        return wizard

    async def process_step(
        self, session_id: str, user_input: dict
    ) -> WizardState:
        """사용자 입력을 받아 다음 단계로 진행."""
        session = self._sessions.get(session_id)
        if not session:
            return WizardState(
                session_id=session_id,
                platform="",
                current_step=0,
                total_steps=0,
                step_info=None,
                status="failed",
                message="세션을 찾을 수 없습니다.",
                error="session_not_found",
            )

        wizard = session.wizard
        connector = session.connector
        current_step = session.steps[wizard.current_step - 1]

        # 사용자 입력 저장
        if current_step.action_type == "user_input":
            wizard.credentials.update(user_input)

            # 토큰 저장
            token_map = get_field_to_env_map(wizard.platform)
            for field_name, env_key in token_map.items():
                if field_name in user_input and user_input[field_name]:
                    await self._security.store_token(
                        wizard.platform, env_key, user_input[field_name], actor="wizard"
                    )

        # 다음 단계로
        if wizard.current_step < wizard.total_steps:
            wizard.current_step += 1
            next_step = session.steps[wizard.current_step - 1]
            wizard.step_info = next_step
            wizard.status = "waiting_input"
            wizard.message = next_step.description

            if next_step.auto_executable:
                return await self._execute_auto_step(session_id)

            # invite URL 동적 생성 (Discord 등)
            if next_step.action_type == "user_action" and not next_step.action_url:
                invite_url = await connector.get_invite_url(wizard.credentials)
                if invite_url:
                    next_step.action_url = invite_url
                    wizard.message = f"{next_step.description}\n\n초대 링크: {invite_url}"

            return wizard
        else:
            return await self._finalize(session_id)

    async def _execute_auto_step(self, session_id: str) -> WizardState:
        """자동 실행 단계 처리."""
        session = self._sessions.get(session_id)
        if not session:
            return WizardState(
                session_id=session_id, platform="", current_step=0,
                total_steps=0, step_info=None, status="failed",
                message="세션 없음", error="session_not_found",
            )

        wizard = session.wizard
        connector = session.connector
        wizard.status = "processing"

        # 자격 증명 검증
        validation = await connector.validate_credentials(wizard.credentials)
        if validation.valid:
            # 연결 시도
            result = await connector.connect(wizard.credentials)
            if result.success:
                # 마지막 단계면 완료
                if wizard.current_step >= wizard.total_steps:
                    return await self._finalize(session_id)
                # 아니면 다음 단계
                return await self.process_step(session_id, {})

            wizard.status = "failed"
            wizard.message = result.message
            wizard.error = result.error
            return wizard

        # 검증 실패 — 다음 단계로 (입력 필요)
        if wizard.current_step < wizard.total_steps:
            wizard.current_step += 1
            next_step = session.steps[wizard.current_step - 1]
            wizard.step_info = next_step
            wizard.status = "waiting_input"
            wizard.message = next_step.description
            return wizard

        wizard.status = "failed"
        wizard.message = validation.message
        wizard.error = validation.error
        return wizard

    async def _finalize(self, session_id: str) -> WizardState:
        """위자드 완료: 게이트웨이 시작."""
        session = self._sessions.get(session_id)
        if not session:
            return WizardState(
                session_id=session_id, platform="", current_step=0,
                total_steps=0, step_info=None, status="failed",
                message="세션 없음", error="session_not_found",
            )

        wizard = session.wizard
        platform = wizard.platform

        # 게이트웨이 시작
        success = await self._lifecycle.start_gateway(platform)
        if success:
            wizard.status = "completed"
            wizard.message = f"{platform} 연결이 완료되었습니다!"
            # auto_start 설정 저장
            await self._db.set_setting(
                f"messenger_auto_start:{platform}", True
            )
        else:
            wizard.status = "failed"
            wizard.message = f"{platform} 게이트웨이 시작 실패"
            wizard.error = "gateway_start_failed"

        return wizard

    def get_current_state(self, session_id: str) -> WizardState | None:
        """현재 위자드 상태 조회."""
        session = self._sessions.get(session_id)
        return session.wizard if session else None

    async def cancel(self, session_id: str) -> None:
        """위자드 취소."""
        self._sessions.pop(session_id, None)

    def _cleanup_expired(self) -> None:
        """만료된 세션 정리."""
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.created_at > SESSION_TTL
        ]
        for sid in expired:
            del self._sessions[sid]

    def get_connector(self, platform: str) -> AutoConnector | None:
        """플랫폼별 AutoConnector 조회."""
        return self._connectors.get(platform)
