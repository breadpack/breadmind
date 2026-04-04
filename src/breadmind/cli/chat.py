"""breadmind chat -- 대화형 CLI 채팅 명령."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path


async def run_chat(args) -> None:
    """대화형 CLI 채팅 실행.

    v1 bootstrap의 경량 버전:
    - config 로드
    - LLM provider 생성
    - 기본 도구 레지스트리
    - MessageLoopAgent + 스트리밍
    - ConversationStore (대화 저장/복원)
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

    async def cli_approval(request: ApprovalRequest) -> ApprovalResponse:
        print(f"\n[!] Approval required: {request.tool_name}")
        print(f"    Reason: {request.reason}")
        print(f"    Arguments: {request.arguments}")
        answer = await asyncio.get_running_loop().run_in_executor(
            None, lambda: input("    Execute? (y/n): ").strip().lower(),
        )
        return ApprovalResponse(
            request_id=request.request_id,
            approved=answer in ("y", "yes"),
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

    # 12. 세션 관리
    session_id = args.continue_session or f"chat_{uuid.uuid4().hex[:8]}"
    resume = args.continue_session is not None

    from breadmind.core.protocols import AgentContext
    use_stream = args.stream and not args.no_stream

    print(f"BreadMind CLI Chat [{'streaming' if use_stream else 'standard'}]")
    print(f"  Session: {session_id}")
    if resume:
        print("  Resuming previous session...")
    print("  Type 'exit' to quit, '/sessions' to list sessions")
    print("-" * 50)

    # 13. 대화 루프
    await _chat_loop(agent, conversation_store, session_id, resume, use_stream)


async def _chat_loop(
    agent, conversation_store, session_id: str, resume: bool, use_stream: bool,
) -> None:
    """메인 대화 루프."""
    from breadmind.core.protocols import AgentContext

    while True:
        try:
            user_input = await asyncio.get_running_loop().run_in_executor(
                None, lambda: input("\nyou> ").strip(),
            )
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            print("Goodbye!")
            break
        if user_input == "/sessions":
            if conversation_store:
                sessions = await conversation_store.list_conversations()
                for s in sessions:
                    print(f"  {s.session_id} | {s.title} | {s.updated_at}")
            else:
                print("  No conversation store available.")
            continue

        # 이미지 경로 감지 시 안내 메시지 출력
        from breadmind.plugins.builtin.tools.multimodal import extract_image_paths
        detected_paths = extract_image_paths(user_input)
        if detected_paths:
            from pathlib import Path as _Path
            valid = [p for p in detected_paths if _Path(p).exists()]
            if valid:
                names = ", ".join(_Path(p).name for p in valid)
                print(f"  [image detected: {names}]")

        ctx = AgentContext(
            user="cli_user", channel="cli",
            session_id=session_id, resume=resume,
        )
        resume = False  # 첫 턴만 resume

        if use_stream:
            await _handle_stream(agent, user_input, ctx)
        else:
            resp = await agent.handle_message(user_input, ctx)
            print(f"\nbreadmind> {resp.content}\n")


async def _handle_stream(agent, user_input: str, ctx) -> None:
    """스트리밍 응답 처리."""
    async for event in agent.handle_message_stream(user_input, ctx):
        if event.type == "text":
            print(event.data, end="", flush=True)
        elif event.type == "tool_start":
            tools = event.data.get("tools", [])
            print(f"\n  [tool: {', '.join(tools)}]", flush=True)
        elif event.type == "tool_end":
            results = event.data.get("results", [])
            status = ", ".join(
                f"{r['name']}:{'ok' if r['success'] else 'fail'}" for r in results
            )
            print(f"  [{status}]", flush=True)
        elif event.type == "error":
            print(f"\n  [error: {event.data}]", flush=True)
        elif event.type == "done":
            tokens = event.data.get("tokens", 0)
            tc = event.data.get("tool_calls", 0)
            print(f"\n  [{tokens} tokens, {tc} tools]\n", flush=True)
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
