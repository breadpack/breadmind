"""Pydantic v2 validation layer for BreadMind configuration.

Since the core config classes (in ``breadmind.config`` and
``breadmind.config_types``) are now Pydantic BaseModel subclasses,
this module simply re-exports the root model and provides thin
validation helpers.

Usage::

    from breadmind.core.config_schema import validate_config, validate_config_file

    schema = validate_config(raw_yaml_dict)
    schema = validate_config_file("config/config.yaml")
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from breadmind.config import AppConfig

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
AppConfigSchema = AppConfig


def validate_config(raw_dict: dict) -> AppConfig:
    """Validate a raw YAML dictionary against :class:`AppConfig`.

    Parameters
    ----------
    raw_dict:
        A dictionary typically produced by ``yaml.safe_load()``.

    Returns
    -------
    AppConfig
        The validated configuration object.

    Raises
    ------
    pydantic.ValidationError
        If validation fails.  The exception contains structured error
        details including the path to each invalid field.
    """
    try:
        return AppConfig.model_validate(raw_dict)
    except ValidationError:
        logger.error("Configuration validation failed. Details follow.")
        raise


def validate_config_file(path: str | Path) -> AppConfig:
    """Read a YAML config file and validate it.

    Parameters
    ----------
    path:
        Filesystem path to the YAML configuration file.

    Returns
    -------
    AppConfig
        The validated configuration object.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    pydantic.ValidationError
        If the content fails schema validation.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as fh:
        raw = yaml.safe_load(fh) or {}

    return validate_config(raw)
