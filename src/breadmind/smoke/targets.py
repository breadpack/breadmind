"""PilotTargets: the single source of truth for what smoke must verify.

Loaded from ``deploy/smoke/pilot-targets.yaml``. Strict schema — unknown
keys raise ``TargetsError`` so that a typo does not silently turn into a
false PASS.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class TargetsError(RuntimeError):
    """Raised when ``pilot-targets.yaml`` is missing, malformed, or has
    unknown/invalid keys."""


@dataclass(frozen=True)
class SlackTargets:
    required_channels: list[str]
    required_events: list[str]


@dataclass(frozen=True)
class ConfluenceTargets:
    base_url: str
    required_spaces: list[str]


@dataclass(frozen=True)
class AnthropicTargets:
    required_models: list[str]


@dataclass(frozen=True)
class AzureTargets:
    endpoint_env: str
    required_deployments: list[str]


@dataclass(frozen=True)
class LlmTargets:
    anthropic: AnthropicTargets
    azure: AzureTargets
    no_training_confirmed: bool


@dataclass(frozen=True)
class PilotTargets:
    migration_head: str
    slack: SlackTargets
    confluence: ConfluenceTargets
    llm: LlmTargets


_TOP_LEVEL_KEYS = {"migration_head", "slack", "confluence", "llm"}
_SLACK_KEYS = {"required_channels", "required_events"}
_CONFLUENCE_KEYS = {"base_url", "required_spaces"}
_LLM_KEYS = {"anthropic", "azure", "no_training_confirmed"}
_ANTHROPIC_KEYS = {"required_models"}
_AZURE_KEYS = {"endpoint_env", "required_deployments"}


def _require_keys(d: dict[str, Any], allowed: set[str], where: str) -> None:
    if not isinstance(d, dict):
        raise TargetsError(f"{where} must be a mapping")
    unknown = set(d.keys()) - allowed
    missing = allowed - set(d.keys())
    if unknown:
        raise TargetsError(f"{where}: unknown keys {sorted(unknown)}")
    if missing:
        raise TargetsError(f"{where}: missing keys {sorted(missing)}")


def load_targets(path: Path) -> PilotTargets:
    if not path.exists():
        raise TargetsError(f"targets file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TargetsError(f"YAML parse error: {exc}") from exc
    if raw is None:
        raise TargetsError("targets file is empty")

    _require_keys(raw, _TOP_LEVEL_KEYS, "root")
    _require_keys(raw["slack"], _SLACK_KEYS, "slack")
    _require_keys(raw["confluence"], _CONFLUENCE_KEYS, "confluence")
    _require_keys(raw["llm"], _LLM_KEYS, "llm")
    _require_keys(raw["llm"]["anthropic"], _ANTHROPIC_KEYS, "llm.anthropic")
    _require_keys(raw["llm"]["azure"], _AZURE_KEYS, "llm.azure")

    return PilotTargets(
        migration_head=str(raw["migration_head"]),
        slack=SlackTargets(
            required_channels=[str(c) for c in raw["slack"]["required_channels"]],
            required_events=[str(e) for e in raw["slack"]["required_events"]],
        ),
        confluence=ConfluenceTargets(
            base_url=str(raw["confluence"]["base_url"]),
            required_spaces=[str(s) for s in raw["confluence"]["required_spaces"]],
        ),
        llm=LlmTargets(
            anthropic=AnthropicTargets(
                required_models=[str(m) for m in raw["llm"]["anthropic"]["required_models"]],
            ),
            azure=AzureTargets(
                endpoint_env=str(raw["llm"]["azure"]["endpoint_env"]),
                required_deployments=[
                    str(d) for d in raw["llm"]["azure"]["required_deployments"]
                ],
            ),
            no_training_confirmed=bool(raw["llm"]["no_training_confirmed"]),
        ),
    )
