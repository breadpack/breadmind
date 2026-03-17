import asyncio
import fnmatch
import logging
import os
import re
import shlex
import sys
from pathlib import Path
from breadmind.messenger.auto_connect.base import _get_base_url
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)

DANGEROUS_PATTERNS: list[str] = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    ">()",
    "chmod -R 777 /",
]

SENSITIVE_FILE_PATTERNS: list[str] = [
    ".env",
    "*credentials*",
    "*secret*",
    "*.key",
    "*.pem",
]

# Configurable base directory for path validation
BASE_DIRECTORY: str = os.getcwd()

# Allowed SSH hosts (empty means all are blocked except localhost)
ALLOWED_SSH_HOSTS: list[str] = []

# Shell metacharacters that indicate potential command injection
SHELL_META_CHARS = re.compile(r'[;&|`$]')


def _get_known_hosts() -> str | None:
    """Return the path to known_hosts for SSH host key verification.

    By default, uses ``~/.ssh/known_hosts`` (created if absent).
    Set ``BREADMIND_SSH_STRICT_HOST_KEY=false`` to explicitly disable verification.
    """
    strict = os.environ.get("BREADMIND_SSH_STRICT_HOST_KEY", "true").lower()
    if strict == "false":
        logger.warning(
            "SSH host key verification disabled by BREADMIND_SSH_STRICT_HOST_KEY=false"
        )
        return None
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if not known_hosts.exists():
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        known_hosts.touch(mode=0o644)
    return str(known_hosts)


class ToolSecurityConfig:
    """Runtime-configurable security settings for builtin tools."""

    _dangerous_patterns: list[str] = list(DANGEROUS_PATTERNS)
    _sensitive_patterns: list[str] = list(SENSITIVE_FILE_PATTERNS)
    _allowed_ssh_hosts: list[str] = list(ALLOWED_SSH_HOSTS)
    _base_directory: str = str(Path.cwd())
    _command_whitelist: list[str] = []  # If non-empty, only these commands allowed
    _command_whitelist_enabled: bool = False

    @classmethod
    def update(cls, dangerous_patterns=None, sensitive_patterns=None,
               allowed_ssh_hosts=None, base_directory=None):
        if dangerous_patterns is not None:
            cls._dangerous_patterns = dangerous_patterns
        if sensitive_patterns is not None:
            cls._sensitive_patterns = sensitive_patterns
        if allowed_ssh_hosts is not None:
            cls._allowed_ssh_hosts = allowed_ssh_hosts
        if base_directory is not None:
            cls._base_directory = base_directory

    @classmethod
    def set_command_whitelist(cls, commands: list[str], enabled: bool = True):
        cls._command_whitelist = commands
        cls._command_whitelist_enabled = enabled

    @classmethod
    def get_config(cls) -> dict:
        return {
            "dangerous_patterns": cls._dangerous_patterns,
            "sensitive_file_patterns": cls._sensitive_patterns,
            "allowed_ssh_hosts": cls._allowed_ssh_hosts,
            "base_directory": cls._base_directory,
            "command_whitelist": cls._command_whitelist,
            "command_whitelist_enabled": cls._command_whitelist_enabled,
        }

    @classmethod
    def reset(cls):
        """Reset to module-level defaults."""
        cls._dangerous_patterns = list(DANGEROUS_PATTERNS)
        cls._sensitive_patterns = list(SENSITIVE_FILE_PATTERNS)
        cls._allowed_ssh_hosts = list(ALLOWED_SSH_HOSTS)
        cls._base_directory = str(Path.cwd())
        cls._command_whitelist = []
        cls._command_whitelist_enabled = False


def _is_dangerous_command(command: str) -> bool:
    """Check if a command matches any dangerous pattern."""
    cmd_lower = command.lower().strip()
    for pattern in ToolSecurityConfig._dangerous_patterns:
        if pattern.lower() in cmd_lower:
            return True
    return False


def _has_shell_metacharacters(command: str) -> bool:
    """Return True if the command contains shell metacharacters (pipes, chains, etc.)."""
    return bool(SHELL_META_CHARS.search(command))


def _is_command_allowed(command: str) -> tuple[bool, str]:
    """Check if command is allowed. Returns (allowed, reason)."""
    config = ToolSecurityConfig

    # Whitelist mode (if enabled, only whitelisted commands pass)
    if config._command_whitelist_enabled and config._command_whitelist:
        cmd_base = command.split()[0] if command.split() else ""
        if not any(cmd_base.startswith(w) for w in config._command_whitelist):
            return False, f"Command '{cmd_base}' not in whitelist"

    # Blacklist check (existing)
    if _is_dangerous_command(command):
        return False, "Command matches dangerous pattern"

    return True, ""


def _validate_path(path: str) -> Path:
    """Validate that a path doesn't escape the base directory or access sensitive files.

    Returns the resolved Path if valid, raises ValueError otherwise.
    """
    p = Path(path).resolve()
    base = Path(ToolSecurityConfig._base_directory).resolve()

    # Check symlink traversal: resolved path must be under base
    try:
        p.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: {path} resolves outside base directory {base}"
        )

    # Block symbolic link access (resolve() already followed the link above,
    # but we explicitly reject symlinks to prevent confusion)
    if Path(path).is_symlink():
        raise ValueError(f"Symbolic link access blocked: {path}")

    # Check sensitive file patterns against filename AND every path component
    for pattern in ToolSecurityConfig._sensitive_patterns:
        if fnmatch.fnmatch(p.name.lower(), pattern.lower()):
            raise ValueError(f"Access to sensitive file blocked: {p.name}")
        for part in p.parts:
            if fnmatch.fnmatch(part.lower(), pattern.lower()):
                raise ValueError(f"Access to sensitive path blocked: {path}")

    return p


@tool(description="Execute a shell command locally, via SSH, or in an isolated Docker container. Use host='localhost' for local commands. Set container=True for Docker isolation.")
async def shell_exec(command: str, host: str = "localhost", timeout: int = 30,
                     port: int = 22, username: str = None,
                     key_file: str = None, container: bool = False,
                     image: str = None) -> str:
    # Check if command is allowed (whitelist + blacklist)
    allowed, reason = _is_command_allowed(command)
    if not allowed:
        return f"Error: Command blocked - {reason}: {command}"

    # Container isolation mode
    if container and host == "localhost":
        try:
            from breadmind.core.container import ContainerExecutor
            executor = ContainerExecutor()
            result = await executor.run_command(command, image=image, timeout=timeout)
            if result.error:
                return f"Container error: {result.error}"
            output = result.stdout
            if result.exit_code != 0:
                output += f"\nExit code: {result.exit_code}"
            return output.strip() if output else "(no output)"
        except Exception as e:
            return f"Container execution failed: {e}"

    if host == "localhost":
        is_windows = sys.platform == "win32"
        needs_shell = _has_shell_metacharacters(command)

        try:
            if needs_shell:
                # Shell required for pipes, chains, etc. — already validated
                # by _is_command_allowed above
                logger.debug("Using subprocess_shell for command with metacharacters")
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            elif is_windows:
                # Windows without metacharacters: still use shell for cmd built-ins
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                args = shlex.split(command)
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
        except FileNotFoundError:
            return f"Error: Command not found: {command}"
        except OSError as e:
            return f"Error: Failed to execute command: {e}"

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command timed out after {timeout}s: {command}")

        encoding = "cp949" if is_windows else "utf-8"
        output = stdout.decode(encoding, errors="replace")
        errors = stderr.decode(encoding, errors="replace")
        result = output
        if errors:
            result += f"\nSTDERR: {errors}"
        if proc.returncode != 0:
            result += f"\nExit code: {proc.returncode}"
        return result.strip()
    else:
        # Validate SSH host
        if ToolSecurityConfig._allowed_ssh_hosts and host not in ToolSecurityConfig._allowed_ssh_hosts:
            return f"Error: SSH host not allowed: {host}. Allowed hosts: {ToolSecurityConfig._allowed_ssh_hosts}"

        try:
            import asyncssh
        except ImportError:
            return "Error: asyncssh not installed. Install with: pip install asyncssh"
        try:
            known_hosts = _get_known_hosts()
            if known_hosts is None:
                logger.warning(
                    "SSH connection to %s:%d with known_hosts=None — "
                    "host key verification is disabled", host, port,
                )
            connect_kwargs: dict = {
                "host": host,
                "port": port,
                "known_hosts": known_hosts,
            }
            if username is not None:
                connect_kwargs["username"] = username
            if key_file is not None:
                connect_kwargs["client_keys"] = [key_file]
            async with asyncssh.connect(**connect_kwargs) as conn:
                result = await asyncio.wait_for(conn.run(command), timeout=timeout)
                output = result.stdout or ""
                if result.stderr:
                    output += f"\nSTDERR: {result.stderr}"
                return output.strip()
        except Exception as e:
            return f"SSH error: {e}"


@tool(description="Search the web for information using DuckDuckGo")
async def web_search(query: str, limit: int = 5) -> str:
    results = await _duckduckgo_search(query, limit)
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"**{r.get('title', 'No title')}**")
        lines.append(f"  URL: {r.get('href', '')}")
        lines.append(f"  {r.get('body', '')}")
        lines.append("")
    return "\n".join(lines).strip()


async def _duckduckgo_search(query: str, limit: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=limit))
    except ImportError:
        return [{"title": "Error", "href": "", "body": "duckduckgo-search not installed"}]
    except Exception as e:
        return [{"title": "Error", "href": "", "body": str(e)}]


@tool(description="Read content from a file")
async def file_read(path: str, encoding: str = "utf-8") -> str:
    try:
        p = _validate_path(path)
        if not p.exists():
            return f"Error: File not found: {path}"
        return p.read_text(encoding=encoding)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool(description="Write content to a file")
async def file_write(path: str, content: str, encoding: str = "utf-8") -> str:
    try:
        p = _validate_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return f"Written {len(content)} bytes to {path}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool(description="Connect a messenger platform (slack, discord, telegram, whatsapp, gmail, signal). Returns a URL that the user's browser will automatically open for OAuth authorization. Use when user asks to connect/integrate a messenger.")
async def messenger_connect(platform: str) -> str:
    """Generate connection URL for a messenger platform."""
    platform = platform.lower().strip()
    valid = {"slack", "discord", "telegram", "whatsapp", "gmail", "signal"}
    if platform not in valid:
        return f"Invalid platform '{platform}'. Choose from: {', '.join(valid)}"

    # Try orchestrator-based auto-connect first
    if _orchestrator is not None:
        try:
            state = await _orchestrator.start_connection(platform, "chat")
            if state.status == "failed":
                logger.warning("Orchestrator failed for %s, falling back to legacy: %s", platform, state.error)
            else:
                msg = state.message or f"{platform} 연결 위자드가 시작되었습니다."
                if state.step_info and state.step_info.action_url:
                    msg += f"\n[OPEN_URL]{state.step_info.action_url}[/OPEN_URL]"
                msg += f"\n(세션 ID: {state.session_id})"
                return msg
        except Exception as e:
            logger.warning("Orchestrator error for %s, falling back to legacy: %s", platform, e)

    # Legacy behavior (fallback)
    if platform == "whatsapp":
        sid = os.environ.get("WHATSAPP_TWILIO_ACCOUNT_SID", "")
        if sid:
            return "WhatsApp (Twilio)이 설정되어 있습니다. Settings 페이지에서 Webhook URL을 Twilio 콘솔에 등록해주세요."
        else:
            return "[OPEN_URL]https://console.twilio.com/[/OPEN_URL] Twilio 콘솔을 열었습니다. WhatsApp Sandbox를 설정하고 Account SID, Auth Token을 Settings 페이지에서 입력해주세요."

    elif platform == "gmail":
        client_id = os.environ.get("GMAIL_CLIENT_ID", "")
        if client_id:
            base_url = _get_base_url()
            redirect_uri = f"{base_url}/api/messenger/gmail/oauth-callback"
            scopes = "https://www.googleapis.com/auth/gmail.modify"
            url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scopes}&access_type=offline&prompt=consent"
            return f"[OPEN_URL]{url}[/OPEN_URL] Gmail OAuth 페이지를 열었습니다. Google 계정 접근을 허용해주세요."
        else:
            return "[OPEN_URL]https://console.cloud.google.com/apis/credentials[/OPEN_URL] Google Cloud Console을 열었습니다. OAuth 2.0 Client ID를 만들고 Client ID, Client Secret을 Settings 페이지에서 입력해주세요."

    elif platform == "signal":
        return "Signal은 signal-cli를 사용합니다. signal-cli를 설치하고 (https://github.com/AsamK/signal-cli) 전화번호를 등록한 후, Settings 페이지에서 전화번호를 입력해주세요."

    elif platform == "slack":
        client_id = os.environ.get("SLACK_CLIENT_ID", "")
        if client_id:
            base_url = _get_base_url()
            redirect_uri = f"{base_url}/api/messenger/slack/oauth-callback"
            scopes = "chat:write,app_mentions:read,channels:read,im:read,im:write,im:history"
            url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scopes}&redirect_uri={redirect_uri}"
            return f"[OPEN_URL]{url}[/OPEN_URL] Slack OAuth 페이지를 열었습니다. 브라우저에서 워크스페이스 접근을 허용해주세요."
        else:
            return "[OPEN_URL]https://api.slack.com/apps[/OPEN_URL] Slack App이 아직 설정되지 않았습니다. 브라우저에서 Slack API 페이지를 열었습니다. 새 앱을 만들고 Bot Token(xoxb-...)과 App Token(xapp-...)을 Settings 페이지에서 입력해주세요."

    elif platform == "discord":
        client_id = os.environ.get("DISCORD_CLIENT_ID", "")
        if client_id:
            permissions = 274877975552
            url = f"https://discord.com/oauth2/authorize?client_id={client_id}&permissions={permissions}&scope=bot"
            return f"[OPEN_URL]{url}[/OPEN_URL] Discord 봇 초대 페이지를 열었습니다. 서버를 선택하고 인증해주세요."
        else:
            return "[OPEN_URL]https://discord.com/developers/applications[/OPEN_URL] Discord Application이 아직 설정되지 않았습니다. 브라우저에서 Developer Portal을 열었습니다. 새 Application을 만들고 Bot Token을 Settings 페이지에서 입력해주세요."

    elif platform == "telegram":
        return "[OPEN_URL]https://t.me/BotFather[/OPEN_URL] Telegram BotFather를 열었습니다. /newbot 명령으로 봇을 만들고, 발급된 토큰을 Settings 페이지의 Telegram Bot Token 필드에 입력해주세요."


# --- Orchestrator for auto-connect ---
_orchestrator = None


def set_orchestrator(orchestrator):
    """Wire the connection orchestrator for messenger_connect tool."""
    global _orchestrator
    _orchestrator = orchestrator


# --- Swarm role management ---
_swarm_manager = None
_swarm_db = None


def set_swarm_manager(manager, db=None):
    """Wire the swarm manager so chat tools can manage roles."""
    global _swarm_manager, _swarm_db
    _swarm_manager = manager
    _swarm_db = db


@tool(description="Manage Agent Swarm roles. action: 'list', 'add', 'update', or 'remove'. For add/update, provide name, system_prompt, and description.")
async def swarm_role(action: str, name: str = "", system_prompt: str = "", description: str = "") -> str:
    if _swarm_manager is None:
        return "Swarm manager not configured."

    if action == "list":
        roles = _swarm_manager.get_available_roles()
        lines = [f"- **{r['role']}**: {r['description']}" for r in roles]
        return f"Available roles ({len(roles)}):\n" + "\n".join(lines)

    elif action == "add":
        if not name or not system_prompt:
            return "Error: name and system_prompt are required for adding a role."
        name = name.strip().lower().replace(" ", "_")
        _swarm_manager.add_role(name, system_prompt, description or name)
        if _swarm_db:
            try:
                import asyncio
                await _swarm_db.set_setting("swarm_roles", _swarm_manager.export_roles())
            except Exception:
                pass
        return f"Role '{name}' added successfully."

    elif action == "update":
        if not name:
            return "Error: name is required for updating a role."
        _swarm_manager.update_role(name, system_prompt=system_prompt, description=description)
        if _swarm_db:
            try:
                await _swarm_db.set_setting("swarm_roles", _swarm_manager.export_roles())
            except Exception:
                pass
        return f"Role '{name}' updated."

    elif action == "remove":
        if not name:
            return "Error: name is required for removing a role."
        removed = _swarm_manager.remove_role(name)
        if not removed:
            return f"Role '{name}' not found."
        if _swarm_db:
            try:
                await _swarm_db.set_setting("swarm_roles", _swarm_manager.export_roles())
            except Exception:
                pass
        return f"Role '{name}' removed."

    return f"Unknown action: {action}. Use list, add, update, or remove."


@tool(description="Delegate multiple independent tasks to parallel subagents for faster execution. "
      "Use when the user's request contains 2+ independent sub-tasks that can run simultaneously. "
      "Each task gets its own subagent. Results are collected and returned together. "
      "Example: '서버 상태 확인하고 내일 일정도 보여줘' → 2 parallel tasks. "
      "Pass tasks as a JSON array of strings, e.g. [\"서버 상태 확인\", \"내일 일정 조회\"].")
async def delegate_tasks(
    tasks: str,
    _agent: object = None,
    _provider: object = None,
    _registry: object = None,
) -> str:
    """Delegate tasks to parallel subagents."""
    import json as _json

    # Parse tasks (JSON array or comma-separated)
    try:
        task_list = _json.loads(tasks)
    except (_json.JSONDecodeError, TypeError):
        task_list = [t.strip() for t in tasks.split(",") if t.strip()]

    if not isinstance(task_list, list):
        task_list = [str(task_list)]

    if len(task_list) < 2:
        return "단일 작업은 직접 처리합니다. delegate_tasks는 2개 이상의 독립 작업에 사용하세요."

    if not _provider or not _registry:
        return "서브에이전트를 사용할 수 없습니다. (provider/registry not injected)"

    async def run_subtask(task_desc: str, idx: int) -> dict:
        try:
            from breadmind.llm.base import LLMMessage as _LLMMessage
            sub_messages = [
                _LLMMessage(
                    role="system",
                    content=(
                        "You are a focused subagent of BreadMind. "
                        "Complete the given task concisely. Respond in Korean."
                    ),
                ),
                _LLMMessage(role="user", content=task_desc),
            ]

            # Get tool definitions from registry
            all_tools = _registry.get_all_definitions() if _registry else []
            sub_tools = all_tools[:20]  # Limit tools for subagent

            response = await _provider.chat(
                messages=sub_messages,
                tools=sub_tools or None,
                think_budget=3072,
            )

            # Handle tool calls in a simple loop (max 3 turns)
            for _ in range(3):
                if not response.tool_calls:
                    break
                for tc in response.tool_calls:
                    try:
                        result = await _registry.execute(tc.name, tc.arguments)
                        sub_messages.append(_LLMMessage(
                            role="tool",
                            content=f"[success={result.success}] {result.output[:2000]}",
                            tool_call_id=tc.id,
                            name=tc.name,
                        ))
                    except Exception as e:
                        sub_messages.append(_LLMMessage(
                            role="tool",
                            content=f"[success=False] Error: {e}",
                            tool_call_id=tc.id,
                            name=tc.name,
                        ))
                # Add assistant message with tool_calls for context
                sub_messages.append(_LLMMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                ))
                response = await _provider.chat(
                    messages=sub_messages,
                    tools=sub_tools or None,
                    think_budget=1024,
                )

            return {"task": task_desc, "result": response.content or "완료", "success": True}
        except Exception as e:
            logger.warning("Subagent task %d failed: %s", idx, e)
            return {"task": task_desc, "result": f"실패: {e}", "success": False}

    # Run all tasks in parallel
    results = await asyncio.gather(*[run_subtask(task, i) for i, task in enumerate(task_list)])

    # Format results
    lines = [f"## 병렬 처리 결과 ({len(results)}개 작업)\n"]
    for i, r in enumerate(results, 1):
        status = "SUCCESS" if r["success"] else "FAILED"
        lines.append(f"### [{status}] 작업 {i}: {r['task']}\n{r['result']}\n")

    return "\n".join(lines)

# Remove internal injection params from the tool schema so the LLM only sees 'tasks'
_defn = delegate_tasks._tool_definition
for _internal_param in ("_agent", "_provider", "_registry"):
    _defn.parameters.get("properties", {}).pop(_internal_param, None)
    if _internal_param in _defn.parameters.get("required", []):
        _defn.parameters["required"].remove(_internal_param)


def register_builtin_tools(registry) -> None:
    """Register all built-in tools into the given ToolRegistry."""
    for t in [shell_exec, web_search, file_read, file_write, messenger_connect,
              swarm_role, delegate_tasks]:
        registry.register(t)
