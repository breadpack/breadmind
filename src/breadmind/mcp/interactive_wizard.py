"""Interactive MCP server setup wizard with guided configuration."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class WizardStep(str, Enum):
    SELECT_SERVER = "select_server"
    DETECT_RUNTIME = "detect_runtime"
    CONFIGURE_ENV = "configure_env"
    TEST_CONNECTION = "test_connection"
    CONFIRM_INSTALL = "confirm_install"
    COMPLETE = "complete"


@dataclass
class WizardState:
    current_step: WizardStep = WizardStep.SELECT_SERVER
    server_name: str = ""
    server_slug: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    required_env: list[str] = field(default_factory=list)
    optional_env: list[str] = field(default_factory=list)
    runtime: str = ""  # node, python, docker, binary
    test_result: bool = False
    test_message: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class WizardResponse:
    step: WizardStep
    message: str
    needs_input: bool = False
    input_prompt: str = ""
    options: list[str] = field(default_factory=list)
    complete: bool = False
    state: WizardState | None = None


class MCPInteractiveWizard:
    """Guided MCP server setup wizard.

    Walks the user through server installation step-by-step:
    1. Search/select server from registry or provide custom
    2. Auto-detect runtime (Node.js, Python, Docker)
    3. Configure required environment variables
    4. Test connectivity
    5. Confirm and install

    Conversational interface -- user provides input at each step.
    """

    KNOWN_SERVERS: dict[str, dict] = {
        "github": {
            "slug": "modelcontextprotocol/server-github",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "required_env": ["GITHUB_TOKEN"],
            "description": "GitHub API (repos, issues, PRs, code search)",
        },
        "filesystem": {
            "slug": "modelcontextprotocol/server-filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "required_env": [],
            "description": "Local filesystem access",
        },
        "postgres": {
            "slug": "modelcontextprotocol/server-postgres",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-postgres"],
            "required_env": ["POSTGRES_CONNECTION_STRING"],
            "description": "PostgreSQL database access",
        },
        "slack": {
            "slug": "modelcontextprotocol/server-slack",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-slack"],
            "required_env": ["SLACK_BOT_TOKEN"],
            "description": "Slack workspace integration",
        },
        "brave-search": {
            "slug": "modelcontextprotocol/server-brave-search",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-brave-search"],
            "required_env": ["BRAVE_API_KEY"],
            "description": "Brave web search",
        },
        "puppeteer": {
            "slug": "modelcontextprotocol/server-puppeteer",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
            "required_env": [],
            "description": "Browser automation via Puppeteer",
        },
        "sqlite": {
            "slug": "modelcontextprotocol/server-sqlite",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sqlite"],
            "required_env": [],
            "description": "SQLite database access",
        },
        "memory": {
            "slug": "modelcontextprotocol/server-memory",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
            "required_env": [],
            "description": "Knowledge graph memory",
        },
    }

    def __init__(self) -> None:
        self._state = WizardState()
        self._active = False
        self._pending_env_index = 0

    def start(self, server_name: str = "") -> WizardResponse:
        """Start the wizard, optionally with a server name."""
        self._state = WizardState()
        self._active = True
        self._pending_env_index = 0

        if server_name:
            return self._step_select_server(server_name)

        server_list = [
            f"  {name} - {info['description']}"
            for name, info in self.KNOWN_SERVERS.items()
        ]
        options = list(self.KNOWN_SERVERS.keys())

        return WizardResponse(
            step=WizardStep.SELECT_SERVER,
            message=(
                "Welcome to MCP Server Setup Wizard!\n\n"
                "Available pre-configured servers:\n"
                + "\n".join(server_list)
                + "\n\nYou can also enter a custom server name or slug."
            ),
            needs_input=True,
            input_prompt="Enter server name or slug:",
            options=options,
            state=self._state,
        )

    def advance(self, user_input: str = "") -> WizardResponse:
        """Advance the wizard with user input."""
        if not self._active:
            return WizardResponse(
                step=WizardStep.SELECT_SERVER,
                message="Wizard is not active. Call start() first.",
            )

        step = self._state.current_step
        if step == WizardStep.SELECT_SERVER:
            return self._step_select_server(user_input)
        elif step == WizardStep.DETECT_RUNTIME:
            return self._step_detect_runtime()
        elif step == WizardStep.CONFIGURE_ENV:
            return self._step_configure_env(user_input)
        elif step == WizardStep.TEST_CONNECTION:
            return self._step_test_connection()
        elif step == WizardStep.CONFIRM_INSTALL:
            return self._step_confirm(user_input)
        else:
            return WizardResponse(
                step=WizardStep.COMPLETE,
                message="Wizard already complete.",
                complete=True,
                state=self._state,
            )

    def _step_select_server(self, user_input: str) -> WizardResponse:
        """Handle server selection. Check KNOWN_SERVERS first, then treat as custom."""
        name = user_input.strip().lower()

        if name in self.KNOWN_SERVERS:
            info = self.KNOWN_SERVERS[name]
            self._state.server_name = name
            self._state.server_slug = info["slug"]
            self._state.command = info["command"]
            self._state.args = list(info["args"])
            self._state.required_env = list(info.get("required_env", []))
            self._state.optional_env = list(info.get("optional_env", []))
            self._state.current_step = WizardStep.DETECT_RUNTIME
            return self._step_detect_runtime()

        if not name:
            return WizardResponse(
                step=WizardStep.SELECT_SERVER,
                message="Please enter a server name.",
                needs_input=True,
                input_prompt="Enter server name or slug:",
                options=list(self.KNOWN_SERVERS.keys()),
                state=self._state,
            )

        # Custom server
        self._state.server_name = name
        self._state.server_slug = name
        self._state.command = ""
        self._state.args = []
        self._state.current_step = WizardStep.DETECT_RUNTIME
        return self._step_detect_runtime()

    def _step_detect_runtime(self) -> WizardResponse:
        """Auto-detect runtime availability (node, python, docker)."""
        detected = []
        if shutil.which("node") or shutil.which("npx"):
            detected.append("node")
        if shutil.which("python3") or shutil.which("python"):
            detected.append("python")
        if shutil.which("docker"):
            detected.append("docker")

        # If the command is already set (known server), infer runtime
        if self._state.command:
            if self._state.command in ("npx", "node"):
                self._state.runtime = "node"
            elif self._state.command in ("python", "python3", "pip", "uvx", "uv"):
                self._state.runtime = "python"
            elif self._state.command == "docker":
                self._state.runtime = "docker"
            else:
                self._state.runtime = "binary"
        elif detected:
            self._state.runtime = detected[0]
        else:
            self._state.runtime = "unknown"

        runtime_available = self._state.runtime in detected or self._state.runtime == "binary"

        if self._state.required_env:
            self._state.current_step = WizardStep.CONFIGURE_ENV
            self._pending_env_index = 0
            first_var = self._state.required_env[0]
            return WizardResponse(
                step=WizardStep.CONFIGURE_ENV,
                message=(
                    f"Runtime detected: {self._state.runtime} "
                    f"({'available' if runtime_available else 'NOT found'})\n"
                    f"Available runtimes: {', '.join(detected) if detected else 'none'}\n\n"
                    f"This server requires environment variables: "
                    f"{', '.join(self._state.required_env)}"
                ),
                needs_input=True,
                input_prompt=f"Enter value for {first_var}:",
                state=self._state,
            )

        # No env needed, skip to test
        self._state.current_step = WizardStep.TEST_CONNECTION
        return self._step_test_connection()

    def _step_configure_env(self, user_input: str) -> WizardResponse:
        """Collect required environment variables from user one at a time."""
        if self._pending_env_index < len(self._state.required_env):
            var_name = self._state.required_env[self._pending_env_index]
            value = user_input.strip()
            if not value:
                return WizardResponse(
                    step=WizardStep.CONFIGURE_ENV,
                    message=f"{var_name} cannot be empty.",
                    needs_input=True,
                    input_prompt=f"Enter value for {var_name}:",
                    state=self._state,
                )
            self._state.env_vars[var_name] = value
            self._pending_env_index += 1

        # Check if more vars needed
        if self._pending_env_index < len(self._state.required_env):
            next_var = self._state.required_env[self._pending_env_index]
            return WizardResponse(
                step=WizardStep.CONFIGURE_ENV,
                message=f"Set {self._state.required_env[self._pending_env_index - 1]}.",
                needs_input=True,
                input_prompt=f"Enter value for {next_var}:",
                state=self._state,
            )

        # All env vars collected
        self._state.current_step = WizardStep.TEST_CONNECTION
        return self._step_test_connection()

    def _step_test_connection(self) -> WizardResponse:
        """Simulate connection test. In production, would start server briefly."""
        # Validate we have the minimum config
        errors = []
        if not self._state.command and self._state.runtime == "node":
            self._state.command = "npx"
        if not self._state.command and self._state.runtime == "unknown":
            errors.append("No command configured and runtime not detected")

        for var in self._state.required_env:
            if var not in self._state.env_vars:
                errors.append(f"Missing required env var: {var}")

        if errors:
            self._state.test_result = False
            self._state.test_message = "; ".join(errors)
            self._state.errors = errors
        else:
            self._state.test_result = True
            self._state.test_message = "Configuration looks valid"

        self._state.current_step = WizardStep.CONFIRM_INSTALL

        status = "PASSED" if self._state.test_result else "FAILED"
        env_display = ", ".join(
            f"{k}={'*' * min(len(v), 8)}" for k, v in self._state.env_vars.items()
        )

        return WizardResponse(
            step=WizardStep.CONFIRM_INSTALL,
            message=(
                f"Configuration test: {status}\n"
                f"{self._state.test_message}\n\n"
                f"Server: {self._state.server_name}\n"
                f"Command: {self._state.command} {' '.join(self._state.args)}\n"
                f"Runtime: {self._state.runtime}\n"
                f"Env: {env_display or '(none)'}\n\n"
                f"Proceed with installation?"
            ),
            needs_input=True,
            input_prompt="Confirm installation (yes/no):",
            options=["yes", "no"],
            state=self._state,
        )

    def _step_confirm(self, user_input: str) -> WizardResponse:
        """Confirm installation."""
        answer = user_input.strip().lower()
        if answer in ("yes", "y"):
            self._state.current_step = WizardStep.COMPLETE
            self._active = False
            return WizardResponse(
                step=WizardStep.COMPLETE,
                message=(
                    f"MCP server '{self._state.server_name}' is ready to install.\n"
                    f"Use get_install_config() to retrieve the configuration."
                ),
                complete=True,
                state=self._state,
            )
        elif answer in ("no", "n"):
            return self.cancel()
        else:
            return WizardResponse(
                step=WizardStep.CONFIRM_INSTALL,
                message="Please answer 'yes' or 'no'.",
                needs_input=True,
                input_prompt="Confirm installation (yes/no):",
                options=["yes", "no"],
                state=self._state,
            )

    def get_install_config(self) -> dict:
        """Get the final installation configuration."""
        return {
            "name": self._state.server_name,
            "slug": self._state.server_slug,
            "command": self._state.command,
            "args": self._state.args,
            "env": dict(self._state.env_vars),
            "runtime": self._state.runtime,
        }

    def cancel(self) -> WizardResponse:
        """Cancel the wizard."""
        self._active = False
        self._state.current_step = WizardStep.COMPLETE
        return WizardResponse(
            step=WizardStep.COMPLETE,
            message="Wizard cancelled.",
            complete=True,
            state=self._state,
        )

    @property
    def active(self) -> bool:
        return self._active

    @property
    def state(self) -> WizardState:
        return self._state
