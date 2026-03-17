import asyncio
import fnmatch
import logging
import os
import shlex
import sys
from pathlib import Path
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

    # Check sensitive file patterns
    filename = p.name
    for pattern in ToolSecurityConfig._sensitive_patterns:
        if fnmatch.fnmatch(filename.lower(), pattern.lower()):
            raise ValueError(f"Access to sensitive file blocked: {filename}")

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

        try:
            if is_windows:
                # On Windows, use shell=True via create_subprocess_shell
                # to support cmd built-ins, PowerShell, and piped commands
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
            logger.warning(
                "SSH connection to %s:%d with known_hosts=None — "
                "host key verification is disabled", host, port,
            )
            connect_kwargs: dict = {
                "host": host,
                "port": port,
                "known_hosts": None,
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
            port = os.environ.get("BREADMIND_PORT", "8082")
            redirect_uri = f"http://localhost:{port}/api/messenger/gmail/oauth-callback"
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
            port = os.environ.get("BREADMIND_PORT", "8082")
            redirect_uri = f"http://localhost:{port}/api/messenger/slack/oauth-callback"
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


def register_builtin_tools(registry) -> None:
    """Register all built-in tools into the given ToolRegistry."""
    for t in [shell_exec, web_search, file_read, file_write, messenger_connect, swarm_role]:
        registry.register(t)
