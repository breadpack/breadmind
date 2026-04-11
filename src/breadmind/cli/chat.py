"""breadmind chat -- 대화형 CLI 채팅 명령."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from breadmind.cli.session_manager import SessionManager
from breadmind.utils.helpers import generate_short_id
from breadmind.cli.ui import get_ui


async def run_chat(args) -> None:
    """대화형 CLI 채팅 실행.

    v1 bootstrap의 경량 버전:
    - config 로드
    - LLM provider 생성
    - 기본 도구 레지스트리
    - MessageLoopAgent + 스트리밍
    - ConversationStore (대화 저장/복원)
    - SessionManager (세션 저장/복원)
    """
    # 1. Config 로드
    try:
        from breadmind.config import load_config, get_default_config_dir, load_env_file
        config_dir = args.config_dir or get_default_config_dir()
        if os.path.isdir(config_dir) and os.path.exists(os.path.join(config_dir, "config.yaml")):
            config = load_config(config_dir)
        elif os.path.isdir("config"):
            config = load_config("config")
            config_dir = "config"
        else:
            config = load_config(config_dir)  # returns defaults
        config.validate()
        load_env_file(os.path.join(config_dir, ".env"))
    except Exception:
        # Graceful fallback: 최소 config 객체
        config = _make_fallback_config()
        config_dir = os.path.join(Path.home().as_posix(), ".breadmind")

    # 2. Logging
    import logging
    log_level = getattr(args, "log_level", None) or "WARNING"
    logging.basicConfig(
        level=getattr(logging, log_level, logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # 3. Provider 생성
    if args.model:
        config.llm.default_model = args.model
    from breadmind.llm.factory import create_provider
    provider = create_provider(config)

    # 4. 기본 도구 등록
    from breadmind.plugins.builtin.tools.registry import HybridToolRegistry
    registry = HybridToolRegistry()
    _register_basic_tools(registry)
    registry.register_tool_search()

    # 5. Safety
    from breadmind.plugins.builtin.safety.guard import SafetyGuard
    safety = SafetyGuard(autonomy="confirm-destructive")

    # 6. Prompt builder
    from breadmind.core.protocols import PromptContext
    prompt_builder = _create_prompt_builder()
    prompt_context = PromptContext(persona_name="BreadMind", language="ko")

    # 7. ConversationStore (파일 기반)
    conversation_store = None
    try:
        store_dir = os.path.join(config_dir, "conversations")
        os.makedirs(store_dir, exist_ok=True)
        from breadmind.plugins.builtin.memory.conversation_store import ConversationStore
        conversation_store = ConversationStore(file_dir=store_dir)
    except Exception:
        pass

    # 8. AutoCompactor
    from breadmind.plugins.builtin.agent_loop.auto_compact import AutoCompactor
    compactor = AutoCompactor(provider=provider)

    # 9. OutputLimiter
    from breadmind.plugins.builtin.tools.output_limiter import OutputLimiter
    limiter = OutputLimiter()

    # 10. Approval handler (CLI용 -- stdin에서 y/n 입력)
    from breadmind.plugins.builtin.safety.approval import (
        CallbackApprovalHandler, ApprovalRequest, ApprovalResponse,
    )

    ui = get_ui()

    async def cli_approval(request: ApprovalRequest) -> ApprovalResponse:
        ui.warning(f"Approval required: {request.tool_name}")
        ui.info(f"    Reason: {request.reason}")
        ui.info(f"    Arguments: {request.arguments}")
        approved = await asyncio.get_running_loop().run_in_executor(
            None, lambda: ui.confirm("    Execute?"),
        )
        return ApprovalResponse(
            request_id=request.request_id,
            approved=approved,
        )

    approval = CallbackApprovalHandler(cli_approval)

    # 11. MessageLoopAgent 생성
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
    agent = MessageLoopAgent(
        provider=provider,
        prompt_builder=prompt_builder,
        tool_registry=registry,
        safety_guard=safety,
        max_turns=15,
        prompt_context=prompt_context,
        auto_compactor=compactor,
        output_limiter=limiter,
        approval_handler=approval,
        conversation_store=conversation_store,
    )

    # 12. SessionManager
    session_mgr = SessionManager()

    # 13. 세션 관리 -- --continue / --resume 지원
    session_id, resume = await _resolve_session(args, session_mgr, ui)

    use_stream = args.stream and not args.no_stream

    mode = "streaming" if use_stream else "standard"
    panel_lines = [f"Session: {session_id}  |  Mode: {mode}"]
    if resume:
        panel_lines.append("Resuming previous session...")
    panel_lines.append("Type 'exit' to quit, '/sessions' to list sessions")
    ui.panel("BreadMind CLI Chat", "\n".join(panel_lines))

    # 14. 대화 루프
    await _chat_loop(agent, conversation_store, session_id, resume, use_stream, session_mgr)


async def _resolve_session(args, session_mgr: SessionManager, ui) -> tuple[str, bool]:
    """CLI 인자를 기반으로 세션 ID와 resume 여부를 결정."""
    # --continue (-c): 가장 최근 세션 재개
    if getattr(args, "continue_last", False):
        latest = session_mgr.get_latest_session_id()
        if latest:
            ui.info(f"[Resumed session {latest}]")
            return latest, True
        ui.warning("No previous session found. Starting new session.")
        return f"chat_{generate_short_id()}", False

    # --resume (-r): 특정 세션 또는 목록 선택
    resume_val = getattr(args, "resume_session", None)
    if resume_val is not None:
        if resume_val != "":
            # 특정 세션 ID 지정
            loaded = session_mgr.load_session(resume_val)
            if loaded is not None:
                ui.info(f"[Resumed session {resume_val}]")
                return resume_val, True
            ui.warning(f"Session '{resume_val}' not found. Starting new session.")
            return f"chat_{generate_short_id()}", False
        # 빈 값: 목록에서 선택
        sessions = session_mgr.list_sessions(limit=20)
        if not sessions:
            ui.warning("No sessions found. Starting new session.")
            return f"chat_{generate_short_id()}", False

        import datetime
        rows = []
        for i, s in enumerate(sessions, 1):
            ts = datetime.datetime.fromtimestamp(s["timestamp"]).strftime("%Y-%m-%d %H:%M")
            short_id = s["id"][:16]
            rows.append([str(i), short_id, s["preview"] or "(empty)", ts, str(s["message_count"])])
        ui.table(["#", "Session ID", "Last Message", "Updated", "Messages"], rows)

        try:
            choice = await asyncio.get_running_loop().run_in_executor(
                None, lambda: input("Select session number (or Enter to cancel): ").strip(),
            )
            if choice.isdigit() and 1 <= int(choice) <= len(sessions):
                picked = sessions[int(choice) - 1]
                ui.info(f"[Resumed session {picked['id']}]")
                return picked["id"], True
        except (KeyboardInterrupt, EOFError):
            pass
        ui.info("Starting new session.")
        return f"chat_{generate_short_id()}", False

    # --continue (기존 하위 호환) 또는 새 세션
    if args.continue_session:
        return args.continue_session, True
    return f"chat_{generate_short_id()}", False


async def _chat_loop(
    agent, conversation_store, session_id: str, resume: bool, use_stream: bool,
    session_mgr: SessionManager | None = None,
) -> None:
    """메인 대화 루프."""
    from breadmind.core.protocols import AgentContext

    ui = get_ui()

    while True:
        try:
            user_input = await asyncio.get_running_loop().run_in_executor(
                None, lambda: input("\nyou> ").strip(),
            )
        except (KeyboardInterrupt, EOFError):
            ui.info("Goodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            ui.info("Goodbye!")
            break
        if user_input == "/sessions":
            if conversation_store:
                sessions = await conversation_store.list_conversations()
                rows = [[s.session_id, s.title, str(s.updated_at)] for s in sessions]
                ui.table(["Session ID", "Title", "Updated"], rows)
            else:
                ui.warning("No conversation store available.")
            continue

        # 이미지 경로 감지 시 안내 메시지 출력
        from breadmind.plugins.builtin.tools.multimodal import extract_image_paths
        detected_paths = extract_image_paths(user_input)
        if detected_paths:
            from pathlib import Path as _Path
            valid = [p for p in detected_paths if _Path(p).exists()]
            if valid:
                names = ", ".join(_Path(p).name for p in valid)
                ui.info(f"Image detected: {names}")

        ctx = AgentContext(
            user="cli_user", channel="cli",
            session_id=session_id, resume=resume,
        )
        resume = False  # 첫 턴만 resume

        if use_stream:
            await _handle_stream(agent, user_input, ctx)
        else:
            with ui.spinner("Thinking..."):
                resp = await agent.handle_message(user_input, ctx)
            ui.markdown(f"**breadmind>** {resp.content}")

        # 세션 자동 저장
        if session_mgr is not None:
            try:
                _save_current_session(session_mgr, session_id, agent)
            except Exception:
                pass  # 세션 저장 실패는 무시


def _save_current_session(session_mgr: SessionManager, session_id: str, agent) -> None:
    """현재 agent의 대화 이력을 세션으로 저장."""
    # agent에서 메시지 이력 추출 시도
    messages_raw: list[dict] = []
    history = getattr(agent, "messages", None) or getattr(agent, "_messages", None)
    if history:
        for msg in history:
            if hasattr(msg, "role"):
                messages_raw.append({"role": msg.role, "content": msg.content or ""})
            elif isinstance(msg, dict):
                messages_raw.append(msg)
    if messages_raw:
        session_mgr.save_session(session_id, messages_raw)


async def _handle_stream(agent, user_input: str, ctx) -> None:
    """스트리밍 응답 처리."""
    ui = get_ui()
    async for event in agent.handle_message_stream(user_input, ctx):
        if event.type == "text":
            print(event.data, end="", flush=True)
        elif event.type == "tool_start":
            tools = event.data.get("tools", [])
            ui.info(f"tool: {', '.join(tools)}")
        elif event.type == "tool_end":
            results = event.data.get("results", [])
            for r in results:
                if r["success"]:
                    ui.success(f"{r['name']}: ok")
                else:
                    ui.error(f"{r['name']}: fail")
        elif event.type == "error":
            ui.error(str(event.data))
        elif event.type == "done":
            tokens = event.data.get("tokens", 0)
            tc = event.data.get("tool_calls", 0)
            ui.info(f"{tokens} tokens, {tc} tools")
    print()


def _register_basic_tools(registry) -> None:
    """기본 CLI 도구 등록."""
    import asyncio as _asyncio
    from breadmind.core.protocols.tool import ToolDefinition

    # shell_exec
    shell_def = ToolDefinition(
        name="shell_exec",
        description="Execute a shell command and return output.",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        readonly=False,
    )

    async def shell_exec(command: str) -> str:
        proc = await _asyncio.create_subprocess_shell(
            command,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode(errors="replace")
        if stderr:
            output += "\nSTDERR: " + stderr.decode(errors="replace")
        return output[:50000]

    registry.register(shell_def, shell_exec)

    # file_read
    read_def = ToolDefinition(
        name="file_read",
        description="Read a file and return its contents.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        readonly=True,
    )

    async def file_read(path: str) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:50000]

    registry.register(read_def, file_read)

    # file_write
    write_def = ToolDefinition(
        name="file_write",
        description="Write content to a file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        readonly=False,
    )

    async def file_write(path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {path}"

    registry.register(write_def, file_write)


def _create_prompt_builder():
    """CLI용 간단한 프롬프트 빌더."""
    from breadmind.core.protocols import PromptBlock

    class CLIPromptBuilder:
        def build(self, ctx):
            blocks = [
                PromptBlock(
                    section="identity",
                    cacheable=True,
                    priority=0,
                    content=(
                        f"You are {ctx.persona_name}, an AI infrastructure agent. "
                        f"You can execute shell commands, read/write files, and help "
                        f"with system administration. "
                        f"Respond in {ctx.language}. Be concise and practical."
                    ),
                ),
            ]
            if ctx.role:
                blocks.append(PromptBlock(
                    section="role", content=f"Current role: {ctx.role}",
                    cacheable=False, priority=3,
                ))
            if ctx.custom_instructions:
                blocks.append(PromptBlock(
                    section="custom", content=ctx.custom_instructions,
                    cacheable=False, priority=6,
                ))
            return blocks

    return CLIPromptBuilder()


def _make_fallback_config():
    """config 로드 실패 시 최소 설정 객체."""
    from types import SimpleNamespace
    config = SimpleNamespace()
    config.llm = SimpleNamespace(
        default_provider="ollama",
        default_model=None,
    )
    config.validate = lambda: None
    return config
