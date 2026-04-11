"""Phase 1 settings whitelist + validation for the SDUI settings_write action.

The schema is intentionally narrow: only keys explicitly listed here can be
written through the SDUI action handler. Each key has a validator that returns
the cleaned value or raises SettingsValidationError. Credential-style keys
(``apikey:*``) are flagged for routing to the CredentialVault instead of the
plain settings store.
"""
from __future__ import annotations

from typing import Any


class SettingsValidationError(ValueError):
    """Raised when a settings_write payload fails validation."""


_PERSONA_PRESETS = {"professional", "friendly", "concise", "humorous"}
_EMBEDDING_PROVIDERS = {
    "auto", "fastembed", "ollama", "local", "gemini", "openai", "off",
}
_API_KEY_NAMES = {
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
}

_RESTART_REQUIRED_KEYS = {"embedding_config"}

_MAX_INSTRUCTIONS_LEN = 8000
_MAX_TURNS_RANGE = (1, 50)


def is_allowed_key(key: str) -> bool:
    if key in {"llm", "persona", "custom_prompts", "custom_instructions", "embedding_config"}:
        return True
    if key.startswith("apikey:"):
        return key.split(":", 1)[1] in _API_KEY_NAMES
    return False


def is_credential_key(key: str) -> bool:
    return key.startswith("apikey:")


def requires_restart(key: str) -> bool:
    return key in _RESTART_REQUIRED_KEYS


def validate_value(key: str, value: Any) -> Any:
    if key == "llm":
        return _validate_llm(value)
    if key == "persona":
        return _validate_persona(value)
    if key == "custom_prompts":
        return _validate_custom_prompts(value)
    if key == "custom_instructions":
        return _validate_instructions(value)
    if key == "embedding_config":
        return _validate_embedding(value)
    if is_credential_key(key):
        return _validate_credential(value)
    raise SettingsValidationError(f"unknown key: {key}")


def _require_dict(key: str, value: Any) -> dict:
    if not isinstance(value, dict):
        raise SettingsValidationError(f"{key} must be an object")
    return value


def _validate_llm(value: Any) -> dict:
    data = _require_dict("llm", value)
    out: dict[str, Any] = {}
    if "default_provider" in data:
        v = data["default_provider"]
        if not isinstance(v, str) or not v:
            raise SettingsValidationError("default_provider must be a non-empty string")
        out["default_provider"] = v
    if "default_model" in data:
        v = data["default_model"]
        if not isinstance(v, str) or not v:
            raise SettingsValidationError("default_model must be a non-empty string")
        out["default_model"] = v
    if "tool_call_max_turns" in data:
        v = data["tool_call_max_turns"]
        try:
            iv = int(v)
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError("tool_call_max_turns must be int") from exc
        lo, hi = _MAX_TURNS_RANGE
        if not (lo <= iv <= hi):
            raise SettingsValidationError(
                f"tool_call_max_turns must be between {lo} and {hi}"
            )
        out["tool_call_max_turns"] = iv
    if not out:
        raise SettingsValidationError("llm payload empty")
    return out


def _validate_persona(value: Any) -> dict:
    data = _require_dict("persona", value)
    out: dict[str, Any] = {}
    if "name" in data:
        v = data["name"]
        if not isinstance(v, str):
            raise SettingsValidationError("persona.name must be string")
        out["name"] = v
    if "preset" in data:
        v = data["preset"]
        if v not in _PERSONA_PRESETS:
            raise SettingsValidationError(
                f"persona.preset must be one of {sorted(_PERSONA_PRESETS)}"
            )
        out["preset"] = v
    if "language" in data:
        v = data["language"]
        if not isinstance(v, str):
            raise SettingsValidationError("persona.language must be string")
        out["language"] = v
    if "specialties" in data:
        v = data["specialties"]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise SettingsValidationError("persona.specialties must be list[str]")
        out["specialties"] = v
    if not out:
        raise SettingsValidationError("persona payload empty")
    return out


def _validate_custom_prompts(value: Any) -> dict:
    data = _require_dict("custom_prompts", value)
    out: dict[str, Any] = {}
    for field in ("main_system_prompt", "behavior_prompt"):
        if field in data:
            v = data[field]
            if not isinstance(v, str):
                raise SettingsValidationError(f"{field} must be string")
            out[field] = v
    if not out:
        raise SettingsValidationError("custom_prompts payload empty")
    return out


def _validate_instructions(value: Any) -> str:
    if not isinstance(value, str):
        raise SettingsValidationError("custom_instructions must be string")
    if len(value) > _MAX_INSTRUCTIONS_LEN:
        raise SettingsValidationError(
            f"custom_instructions exceeds {_MAX_INSTRUCTIONS_LEN} chars"
        )
    return value


def _validate_embedding(value: Any) -> dict:
    data = _require_dict("embedding_config", value)
    out: dict[str, Any] = {}
    if "provider" in data:
        v = data["provider"]
        if v not in _EMBEDDING_PROVIDERS:
            raise SettingsValidationError(
                f"embedding provider must be one of {sorted(_EMBEDDING_PROVIDERS)}"
            )
        out["provider"] = v
    if "model_name" in data:
        v = data["model_name"]
        if v is not None and not isinstance(v, str):
            raise SettingsValidationError("embedding model_name must be string or null")
        out["model_name"] = v
    if "ollama_base_url" in data:
        v = data["ollama_base_url"]
        if not isinstance(v, str):
            raise SettingsValidationError("ollama_base_url must be string")
        out["ollama_base_url"] = v
    if not out:
        raise SettingsValidationError("embedding_config payload empty")
    return out


def _validate_credential(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise SettingsValidationError("credential value must be non-empty string")
    return value


def mask_credential(value: Any) -> str:
    if not value:
        return "미설정"
    s = str(value)
    if len(s) <= 4:
        return "●" * len(s)
    return "●" * (len(s) - 4) + s[-4:]
