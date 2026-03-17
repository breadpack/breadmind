"""Messenger platform metadata -- Single Source of Truth.

All platform-specific information (tokens, gateway classes, connector classes,
UI fields) is registered here once.  Every other module should query
this registry rather than maintaining its own copy.
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.messenger.router import MessengerGateway

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UIField:
    """UI form field definition for platform setup."""

    name: str
    label: str
    env_key: str  # environment variable name
    placeholder: str = ""
    secret: bool = True


@dataclass(frozen=True)
class PlatformMeta:
    """All metadata for a single messenger platform."""

    name: str  # "slack", "discord", ...
    display_name: str  # "Slack", "Discord", ...
    icon: str  # emoji for UI
    gateway_class_path: str  # e.g. "breadmind.messenger.slack.SlackGateway"
    connector_class_path: str  # e.g. "breadmind.messenger.auto_connect.slack.SlackAutoConnector"
    ui_fields: tuple[UIField, ...] = ()
    description: str = ""

    # -- derived helpers --

    @property
    def required_tokens(self) -> list[str]:
        """Environment variable names required for this platform."""
        return [f.env_key for f in self.ui_fields]

    @property
    def field_to_env_map(self) -> dict[str, str]:
        """Mapping from UI field name to environment variable name."""
        return {f.name: f.env_key for f in self.ui_fields}

    @property
    def ui_field_dicts(self) -> list[dict]:
        """Legacy dict format used by ``PLATFORM_CONFIGS``."""
        return [
            {
                "name": f.name,
                "label": f.label,
                "placeholder": f.placeholder,
                "secret": f.secret,
            }
            for f in self.ui_fields
        ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PLATFORM_REGISTRY: dict[str, PlatformMeta] = {}


def register_platform(meta: PlatformMeta) -> None:
    """Register a platform in the global registry."""
    _PLATFORM_REGISTRY[meta.name] = meta


def get_platform(name: str) -> PlatformMeta | None:
    """Lookup a single platform by name."""
    return _PLATFORM_REGISTRY.get(name)


def get_all_platforms() -> dict[str, PlatformMeta]:
    """Return a *copy* of the full registry."""
    return dict(_PLATFORM_REGISTRY)


def get_platform_names() -> list[str]:
    """Return all registered platform names."""
    return list(_PLATFORM_REGISTRY.keys())


def get_token_env_map() -> dict[str, list[str]]:
    """Return ``{platform: [env_key, ...]}`` for every registered platform."""
    return {p.name: p.required_tokens for p in _PLATFORM_REGISTRY.values()}


def get_field_to_env_map(platform: str) -> dict[str, str]:
    """Return ``{field_name: env_key}`` for a single platform."""
    meta = _PLATFORM_REGISTRY.get(platform)
    if not meta:
        return {}
    return meta.field_to_env_map


def get_platform_configs() -> dict[str, dict]:
    """Legacy-compatible ``PLATFORM_CONFIGS`` dict (name, icon, fields)."""
    return {
        meta.name: {
            "name": meta.display_name,
            "icon": meta.icon,
            "fields": meta.ui_field_dicts,
        }
        for meta in _PLATFORM_REGISTRY.values()
    }


# ---------------------------------------------------------------------------
# Gateway factory (replaces ``lifecycle._create_gateway`` if/elif chain)
# ---------------------------------------------------------------------------

async def create_gateway(platform: str) -> "MessengerGateway":
    """Dynamically import and instantiate a gateway class for *platform*."""
    meta = get_platform(platform)
    if not meta:
        raise ValueError(f"Unknown messenger platform: {platform}")

    module_path, class_name = meta.gateway_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


def create_connector(platform: str):
    """Dynamically import and instantiate an AutoConnector for *platform*."""
    meta = get_platform(platform)
    if not meta or not meta.connector_class_path:
        return None

    module_path, class_name = meta.connector_class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


# ---------------------------------------------------------------------------
# Built-in platform registrations
# ---------------------------------------------------------------------------

register_platform(PlatformMeta(
    name="slack",
    display_name="Slack",
    icon="\U0001f4ac",
    gateway_class_path="breadmind.messenger.slack.SlackGateway",
    connector_class_path="breadmind.messenger.auto_connect.slack.SlackAutoConnector",
    ui_fields=(
        UIField(name="bot_token", label="Bot Token", env_key="SLACK_BOT_TOKEN",
                placeholder="xoxb-...", secret=True),
        UIField(name="app_token", label="App Token (Socket Mode)", env_key="SLACK_APP_TOKEN",
                placeholder="xapp-...", secret=True),
    ),
    description="Slack workspace integration",
))

register_platform(PlatformMeta(
    name="discord",
    display_name="Discord",
    icon="\U0001f3ae",
    gateway_class_path="breadmind.messenger.discord_gw.DiscordGateway",
    connector_class_path="breadmind.messenger.auto_connect.discord.DiscordAutoConnector",
    ui_fields=(
        UIField(name="bot_token", label="Bot Token", env_key="DISCORD_BOT_TOKEN",
                placeholder="Bot token from Discord Developer Portal", secret=True),
    ),
    description="Discord server integration",
))

register_platform(PlatformMeta(
    name="telegram",
    display_name="Telegram",
    icon="\u2708\ufe0f",
    gateway_class_path="breadmind.messenger.telegram_gw.TelegramGateway",
    connector_class_path="breadmind.messenger.auto_connect.telegram.TelegramAutoConnector",
    ui_fields=(
        UIField(name="bot_token", label="Bot Token", env_key="TELEGRAM_BOT_TOKEN",
                placeholder="123456:ABC-DEF... from @BotFather", secret=True),
    ),
    description="Telegram bot integration",
))

register_platform(PlatformMeta(
    name="whatsapp",
    display_name="WhatsApp",
    icon="\U0001f4f1",
    gateway_class_path="breadmind.messenger.whatsapp_gw.WhatsAppGateway",
    connector_class_path="breadmind.messenger.auto_connect.whatsapp.WhatsAppAutoConnector",
    ui_fields=(
        UIField(name="account_sid", label="Twilio Account SID", env_key="WHATSAPP_TWILIO_ACCOUNT_SID",
                placeholder="AC...", secret=True),
        UIField(name="auth_token", label="Twilio Auth Token", env_key="WHATSAPP_TWILIO_AUTH_TOKEN",
                placeholder="Auth token", secret=True),
        UIField(name="from_number", label="WhatsApp Number", env_key="WHATSAPP_FROM_NUMBER",
                placeholder="whatsapp:+14155238886", secret=False),
    ),
    description="WhatsApp via Twilio integration",
))

register_platform(PlatformMeta(
    name="gmail",
    display_name="Gmail",
    icon="\u2709\ufe0f",
    gateway_class_path="breadmind.messenger.gmail_gw.GmailGateway",
    connector_class_path="breadmind.messenger.auto_connect.gmail.GmailAutoConnector",
    ui_fields=(
        UIField(name="client_id", label="OAuth Client ID", env_key="GMAIL_CLIENT_ID",
                placeholder="xxx.apps.googleusercontent.com", secret=True),
        UIField(name="client_secret", label="OAuth Client Secret", env_key="GMAIL_CLIENT_SECRET",
                placeholder="GOCSPX-...", secret=True),
        UIField(name="refresh_token", label="Refresh Token", env_key="GMAIL_REFRESH_TOKEN",
                placeholder="1//...", secret=True),
    ),
    description="Gmail OAuth integration",
))

register_platform(PlatformMeta(
    name="signal",
    display_name="Signal",
    icon="\U0001f4e8",
    gateway_class_path="breadmind.messenger.signal_gw.SignalGateway",
    connector_class_path="breadmind.messenger.auto_connect.signal.SignalAutoConnector",
    ui_fields=(
        UIField(name="phone_number", label="Phone Number", env_key="SIGNAL_PHONE_NUMBER",
                placeholder="+1234567890", secret=False),
        UIField(name="signal_cli_path", label="signal-cli Path", env_key="SIGNAL_CLI_PATH",
                placeholder="signal-cli", secret=False),
    ),
    description="Signal messenger integration via signal-cli",
))

register_platform(PlatformMeta(
    name="teams",
    display_name="Microsoft Teams",
    icon="\U0001f4bc",
    gateway_class_path="breadmind.messenger.teams_gw.TeamsGateway",
    connector_class_path="breadmind.messenger.auto_connect.teams.TeamsAutoConnector",
    ui_fields=(
        UIField(name="app_id", label="Microsoft App ID", env_key="TEAMS_APP_ID",
                placeholder="Azure Bot App ID", secret=True),
        UIField(name="app_password", label="App Password", env_key="TEAMS_APP_PASSWORD",
                placeholder="Azure Bot App Password", secret=True),
    ),
    description="Microsoft Teams bot integration via Bot Framework",
))

register_platform(PlatformMeta(
    name="line",
    display_name="LINE",
    icon="\U0001f4ac",
    gateway_class_path="breadmind.messenger.line_gw.LINEGateway",
    connector_class_path="breadmind.messenger.auto_connect.line.LINEAutoConnector",
    ui_fields=(
        UIField(name="channel_token", label="Channel Access Token", env_key="LINE_CHANNEL_TOKEN",
                placeholder="Channel Access Token from LINE Developers", secret=True),
        UIField(name="channel_secret", label="Channel Secret", env_key="LINE_CHANNEL_SECRET",
                placeholder="Channel Secret from LINE Developers", secret=True),
    ),
    description="LINE Messaging API integration",
))

register_platform(PlatformMeta(
    name="matrix",
    display_name="Matrix",
    icon="\U0001f310",
    gateway_class_path="breadmind.messenger.matrix_gw.MatrixGateway",
    connector_class_path="breadmind.messenger.auto_connect.matrix.MatrixAutoConnector",
    ui_fields=(
        UIField(name="homeserver", label="Homeserver URL", env_key="MATRIX_HOMESERVER_URL",
                placeholder="https://matrix.org", secret=False),
        UIField(name="access_token", label="Access Token", env_key="MATRIX_ACCESS_TOKEN",
                placeholder="Matrix access token", secret=True),
        UIField(name="user_id", label="User ID", env_key="MATRIX_USER_ID",
                placeholder="@bot:matrix.org", secret=False),
    ),
    description="Matrix protocol integration",
))
