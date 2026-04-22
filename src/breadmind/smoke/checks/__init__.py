"""Check registry and default wiring for ``breadmind smoke``."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from breadmind.smoke.checks.anthropic import AnthropicCheck
from breadmind.smoke.checks.azure import AzureOpenAICheck
from breadmind.smoke.checks.base import CheckOutcome, CheckStatus, SmokeCheck
from breadmind.smoke.checks.config import ConfigCheck
from breadmind.smoke.checks.confluence_auth import ConfluenceAuthCheck
from breadmind.smoke.checks.confluence_base_url import ConfluenceBaseUrlCheck
from breadmind.smoke.checks.confluence_spaces import ConfluenceSpacesCheck
from breadmind.smoke.checks.database import DatabaseCheck
from breadmind.smoke.checks.declarative import NoTrainingCheck
from breadmind.smoke.checks.slack_auth import SlackAuthCheck
from breadmind.smoke.checks.slack_channels import SlackChannelsCheck
from breadmind.smoke.checks.slack_events import SlackEventsCheck
from breadmind.smoke.checks.vault import VaultCheck

__all__ = [
    "build_checks",
    "CheckOutcome", "CheckStatus", "SmokeCheck",
]


def build_checks(
    *,
    targets_path: Path,
    vault: Any,
    confluence_email: str,
) -> list[SmokeCheck]:
    """Return the canonical check list in rendering order.

    Tokens default to empty string; the CLI handler fetches them from
    the vault and assigns them to the corresponding check instances
    before invoking the runner.
    """
    return [
        ConfigCheck(path=targets_path),
        DatabaseCheck(),
        VaultCheck(vault=vault),
        SlackAuthCheck(token=""),
        SlackChannelsCheck(token="", bot_user_id=""),
        SlackEventsCheck(app_token=""),
        ConfluenceBaseUrlCheck(),
        ConfluenceAuthCheck(email=confluence_email, api_token=""),
        ConfluenceSpacesCheck(email=confluence_email, api_token=""),
        AnthropicCheck(),
        AzureOpenAICheck(),
        NoTrainingCheck(),
    ]
