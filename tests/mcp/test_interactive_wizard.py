"""Tests for MCPInteractiveWizard guided setup flow."""
from __future__ import annotations

from unittest.mock import patch


from breadmind.mcp.interactive_wizard import (
    MCPInteractiveWizard,
    WizardState,
    WizardStep,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _make_wizard() -> MCPInteractiveWizard:
    return MCPInteractiveWizard()


# ── Start / select ───────────────────────────────────────────────────


def test_start_without_name_shows_options():
    wiz = _make_wizard()
    resp = wiz.start()

    assert wiz.active is True
    assert resp.step == WizardStep.SELECT_SERVER
    assert resp.needs_input is True
    assert "github" in resp.options
    assert "filesystem" in resp.options
    assert len(resp.options) == len(MCPInteractiveWizard.KNOWN_SERVERS)


def test_start_with_known_server_skips_select():
    """Providing a known server name should advance past selection."""
    wiz = _make_wizard()
    wiz.start(server_name="github")

    # Should have moved past SELECT_SERVER
    assert wiz.state.server_name == "github"
    assert wiz.state.command == "npx"
    assert "GITHUB_TOKEN" in wiz.state.required_env


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_start_with_custom_name(mock_which):
    mock_which.return_value = None  # no runtimes available

    wiz = _make_wizard()
    wiz.start(server_name="my-custom-server")

    assert wiz.state.server_name == "my-custom-server"
    assert wiz.state.server_slug == "my-custom-server"
    assert wiz.state.command == ""  # custom, no pre-configured command


def test_select_empty_input_reprompts():
    wiz = _make_wizard()
    wiz.start()
    resp = wiz.advance("")

    assert resp.step == WizardStep.SELECT_SERVER
    assert resp.needs_input is True


# ── Runtime detection ────────────────────────────────────────────────


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_detect_runtime_node(mock_which):
    """Known npx-based server should detect node runtime."""
    mock_which.side_effect = lambda cmd: "/usr/bin/npx" if cmd == "npx" else None

    wiz = _make_wizard()
    wiz.start(server_name="filesystem")

    assert wiz.state.runtime == "node"


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_detect_runtime_no_env_skips_to_test(mock_which):
    """Server with no required env should skip to test connection."""
    mock_which.side_effect = lambda cmd: "/usr/bin/npx" if cmd in ("npx", "node") else None

    wiz = _make_wizard()
    resp = wiz.start(server_name="filesystem")

    # filesystem has no required_env, should go to CONFIRM_INSTALL (via test)
    assert resp.step == WizardStep.CONFIRM_INSTALL
    assert wiz.state.test_result is True


# ── Env configuration ───────────────────────────────────────────────


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_configure_env_collects_variables(mock_which):
    mock_which.return_value = "/usr/bin/npx"

    wiz = _make_wizard()
    resp = wiz.start(server_name="github")

    # Should be asking for GITHUB_TOKEN
    assert resp.step == WizardStep.CONFIGURE_ENV
    assert resp.needs_input is True
    assert "GITHUB_TOKEN" in resp.input_prompt

    # Provide the token
    resp = wiz.advance("ghp_test_token_123")

    # Should move to confirm (via test)
    assert resp.step == WizardStep.CONFIRM_INSTALL
    assert wiz.state.env_vars["GITHUB_TOKEN"] == "ghp_test_token_123"


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_configure_env_rejects_empty(mock_which):
    mock_which.return_value = "/usr/bin/npx"

    wiz = _make_wizard()
    wiz.start(server_name="github")
    resp = wiz.advance("")

    assert resp.step == WizardStep.CONFIGURE_ENV
    assert resp.needs_input is True
    assert "cannot be empty" in resp.message


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_configure_multiple_env_vars(mock_which):
    """Server with multiple required envs should ask for each."""
    mock_which.return_value = "/usr/bin/npx"

    wiz = _make_wizard()
    # Manually set up a server with multiple env vars
    wiz._state = WizardState(
        current_step=WizardStep.CONFIGURE_ENV,
        server_name="test-multi",
        command="npx",
        required_env=["VAR_A", "VAR_B"],
        runtime="node",
    )
    wiz._active = True
    wiz._pending_env_index = 0

    resp = wiz.advance("value_a")
    assert resp.needs_input is True
    assert "VAR_B" in resp.input_prompt

    resp = wiz.advance("value_b")
    assert wiz.state.env_vars == {"VAR_A": "value_a", "VAR_B": "value_b"}
    assert resp.step == WizardStep.CONFIRM_INSTALL


# ── Confirm / cancel ────────────────────────────────────────────────


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_confirm_yes_completes(mock_which):
    mock_which.return_value = "/usr/bin/npx"

    wiz = _make_wizard()
    wiz.start(server_name="filesystem")
    resp = wiz.advance("yes")

    assert resp.complete is True
    assert resp.step == WizardStep.COMPLETE
    assert wiz.active is False


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_confirm_no_cancels(mock_which):
    mock_which.return_value = "/usr/bin/npx"

    wiz = _make_wizard()
    wiz.start(server_name="filesystem")
    resp = wiz.advance("no")

    assert resp.complete is True
    assert "cancelled" in resp.message.lower()
    assert wiz.active is False


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_confirm_invalid_reprompts(mock_which):
    mock_which.return_value = "/usr/bin/npx"

    wiz = _make_wizard()
    wiz.start(server_name="filesystem")
    resp = wiz.advance("maybe")

    assert resp.step == WizardStep.CONFIRM_INSTALL
    assert resp.needs_input is True


# ── Install config ───────────────────────────────────────────────────


@patch("breadmind.mcp.interactive_wizard.shutil.which")
def test_get_install_config(mock_which):
    mock_which.return_value = "/usr/bin/npx"

    wiz = _make_wizard()
    wiz.start(server_name="github")
    wiz.advance("ghp_token")
    wiz.advance("yes")

    config = wiz.get_install_config()
    assert config["name"] == "github"
    assert config["command"] == "npx"
    assert config["env"] == {"GITHUB_TOKEN": "ghp_token"}
    assert config["runtime"] == "node"
    assert isinstance(config["args"], list)


# ── Cancel ───────────────────────────────────────────────────────────


def test_cancel_deactivates_wizard():
    wiz = _make_wizard()
    wiz.start()
    resp = wiz.cancel()

    assert wiz.active is False
    assert resp.complete is True


# ── Advance when inactive ────────────────────────────────────────────


def test_advance_inactive_returns_error():
    wiz = _make_wizard()
    resp = wiz.advance("anything")

    assert "not active" in resp.message.lower()
