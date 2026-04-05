"""Environment-based configuration profile support.

When ``BREADMIND_ENV`` is set (e.g. "development", "staging", "production"),
``load_with_profile`` loads ``config.yaml`` as the base and deep-merges
``config.{env}.yaml`` on top of it.  If the env-specific file does not exist
the base config is returned unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def get_active_env() -> str:
    """Return the active environment name from ``BREADMIND_ENV``.

    Defaults to ``"development"`` when the variable is not set.
    """
    return os.environ.get("BREADMIND_ENV", "development")


def get_profile_path(config_dir: str, env: str) -> str | None:
    """Return the path to ``config.{env}.yaml`` if the file exists, else ``None``."""
    path = Path(config_dir) / f"config.{env}.yaml"
    if path.exists():
        return str(path)
    return None


def merge_configs(base: dict, override: dict) -> dict:
    """Deep-merge *override* into *base* and return a new dict.

    Rules:
    * ``dict`` values are merged recursively.
    * ``list`` and scalar values in *override* replace *base*.
    """
    merged: dict[str, Any] = {}
    for key in base:
        if key in override:
            base_val = base[key]
            over_val = override[key]
            if isinstance(base_val, dict) and isinstance(over_val, dict):
                merged[key] = merge_configs(base_val, over_val)
            else:
                merged[key] = over_val
        else:
            merged[key] = base[key]

    for key in override:
        if key not in base:
            merged[key] = override[key]

    return merged


def load_with_profile(config_dir: str) -> dict:
    """Load ``config.yaml`` and optionally merge an environment profile.

    1. Load ``config.yaml`` as the base dict.
    2. Read ``BREADMIND_ENV`` (defaults to ``"development"``).
    3. If ``config.{env}.yaml`` exists, deep-merge it on top of base.
    4. Return the (possibly merged) dict.
    """
    base_path = Path(config_dir) / "config.yaml"
    if base_path.exists():
        with open(base_path) as f:
            base = yaml.safe_load(f) or {}
    else:
        base = {}

    env = get_active_env()
    profile_path = get_profile_path(config_dir, env)
    if profile_path is not None:
        with open(profile_path) as f:
            override = yaml.safe_load(f) or {}
        return merge_configs(base, override)

    return base
