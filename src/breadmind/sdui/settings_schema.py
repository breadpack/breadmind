"""Phase 1 settings whitelist + validation for the SDUI settings_write action.

The schema is intentionally narrow: only keys explicitly listed here can be
written through the SDUI action handler. Each key has a validator that returns
the cleaned value or raises SettingsValidationError. Credential-style keys
(``apikey:*``) are flagged for routing to the CredentialVault instead of the
plain settings store.
"""
from __future__ import annotations

import uuid
from typing import Any


class SettingsValidationError(ValueError):
    """Raised when a settings_write payload fails validation."""


def _coerce_bool(value: Any, field: str) -> bool:
    """Accept native bools and the strings the SDUI ``select`` widget emits.

    The browser-side renderer can only emit string option values, so a select
    bound to a boolean field arrives here as ``"true"`` or ``"false"``. Coerce
    those to bools and reject anything else so we don't silently swallow bad
    inputs.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
    raise SettingsValidationError(f"{field} must be bool")


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
_SKILL_MARKET_TYPES = {"skills_sh", "skillsmp", "clawhub", "mcp_registry"}

_RESTART_REQUIRED_KEYS = {"embedding_config"}

_MAX_INSTRUCTIONS_LEN = 8000
_MAX_TURNS_RANGE = (1, 50)

_PHASE2_KEYS = {
    "mcp",
    "mcp_servers",
    "skill_markets",
    "safety_blacklist",
    "safety_approval",
    "safety_permissions",
    "tool_security",
    "monitoring_config",
    "scheduler_cron",
    "webhook_endpoints",
}

_PHASE3_KEYS = {
    "memory_gc_config",
    "system_timeouts",
    "retry_config",
    "limits_config",
    "polling_config",
    "agent_timeouts",
    "logging_config",
}

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_LOG_FORMATS = {"json", "text"}


def is_allowed_key(key: str) -> bool:
    if key in {"llm", "persona", "custom_prompts", "custom_instructions", "embedding_config"}:
        return True
    if key in _PHASE2_KEYS:
        return True
    if key in _PHASE3_KEYS:
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
    # Phase 2
    if key == "mcp":
        return _validate_mcp(value)
    if key == "mcp_servers":
        return _validate_mcp_servers(value)
    if key == "skill_markets":
        return _validate_skill_markets(value)
    if key == "safety_blacklist":
        return _validate_safety_blacklist(value)
    if key == "safety_approval":
        return _validate_safety_approval(value)
    if key == "safety_permissions":
        return _validate_safety_permissions(value)
    if key == "tool_security":
        return _validate_tool_security(value)
    if key == "monitoring_config":
        return _validate_monitoring_config(value)
    if key == "scheduler_cron":
        return _validate_scheduler_cron(value)
    if key == "webhook_endpoints":
        return _validate_webhook_endpoints(value)
    # Phase 3
    if key == "memory_gc_config":
        return _validate_memory_gc_config(value)
    if key == "system_timeouts":
        return _validate_system_timeouts(value)
    if key == "retry_config":
        return _validate_retry_config(value)
    if key == "limits_config":
        return _validate_limits_config(value)
    if key == "polling_config":
        return _validate_polling_config(value)
    if key == "agent_timeouts":
        return _validate_agent_timeouts(value)
    if key == "logging_config":
        return _validate_logging_config(value)
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


# ---------------------------------------------------------------------------
# Phase 2 validators
# ---------------------------------------------------------------------------

def _validate_mcp(value: Any) -> dict:
    data = _require_dict("mcp", value)
    out: dict[str, Any] = {}
    if "auto_discover" in data:
        out["auto_discover"] = _coerce_bool(data["auto_discover"], "mcp.auto_discover")
    if "max_restart_attempts" in data:
        v = data["max_restart_attempts"]
        try:
            iv = int(v)
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError("mcp.max_restart_attempts must be int") from exc
        if iv < 0:
            raise SettingsValidationError("mcp.max_restart_attempts must be >= 0")
        out["max_restart_attempts"] = iv
    if not out:
        raise SettingsValidationError("mcp payload empty")
    return out


def _validate_mcp_servers(value: Any) -> list:
    if not isinstance(value, list):
        raise SettingsValidationError("mcp_servers must be a list")
    out = []
    seen_names: set[str] = set()
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise SettingsValidationError(f"mcp_servers[{i}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise SettingsValidationError(f"mcp_servers[{i}].name must be a non-empty string")
        if name in seen_names:
            raise SettingsValidationError(f"mcp_servers: duplicate name {name!r}")
        seen_names.add(name)
        command = item.get("command")
        if not isinstance(command, str) or not command:
            raise SettingsValidationError(f"mcp_servers[{i}].command must be a non-empty string")
        args = item.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise SettingsValidationError(f"mcp_servers[{i}].args must be list[str]")
        env = item.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            raise SettingsValidationError(f"mcp_servers[{i}].env must be dict[str, str]")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise SettingsValidationError(f"mcp_servers[{i}].enabled must be bool")
        out.append({"name": name, "command": command, "args": args, "env": env, "enabled": enabled})
    return out


def _validate_skill_markets(value: Any) -> list:
    if not isinstance(value, list):
        raise SettingsValidationError("skill_markets must be a list")
    out = []
    seen_names: set[str] = set()
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise SettingsValidationError(f"skill_markets[{i}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise SettingsValidationError(f"skill_markets[{i}].name must be a non-empty string")
        if name in seen_names:
            raise SettingsValidationError(f"skill_markets: duplicate name {name!r}")
        seen_names.add(name)
        mtype = item.get("type")
        if mtype not in _SKILL_MARKET_TYPES:
            raise SettingsValidationError(
                f"skill_markets[{i}].type must be one of {sorted(_SKILL_MARKET_TYPES)}"
            )
        enabled = _coerce_bool(item.get("enabled", True), f"skill_markets[{i}].enabled")
        entry: dict[str, Any] = {"name": name, "type": mtype, "enabled": enabled}
        if "url" in item:
            url = item["url"]
            if not isinstance(url, str):
                raise SettingsValidationError(f"skill_markets[{i}].url must be string")
            entry["url"] = url
        out.append(entry)
    return out


def _validate_safety_blacklist(value: Any) -> dict:
    if not isinstance(value, dict):
        raise SettingsValidationError("safety_blacklist must be an object")
    out: dict[str, list[str]] = {}
    for domain, tools in value.items():
        if not isinstance(domain, str):
            raise SettingsValidationError("safety_blacklist keys must be strings")
        if not isinstance(tools, list):
            raise SettingsValidationError(
                f"safety_blacklist[{domain!r}] must be a list of tool names"
            )
        for tool in tools:
            if not isinstance(tool, str) or not tool:
                raise SettingsValidationError(
                    f"safety_blacklist[{domain!r}] contains an invalid tool name"
                )
        out[domain] = list(tools)
    return out


def _validate_safety_approval(value: Any) -> list:
    if not isinstance(value, list):
        raise SettingsValidationError("safety_approval must be a list of tool name strings")
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise SettingsValidationError(
                f"safety_approval[{i}] must be a non-empty string"
            )
    return list(value)


def _validate_safety_permissions(value: Any) -> dict:
    data = _require_dict("safety_permissions", value)
    out: dict[str, Any] = {}
    if "user_permissions" in data:
        up = data["user_permissions"]
        if not isinstance(up, dict):
            raise SettingsValidationError("safety_permissions.user_permissions must be an object")
        for user, tools in up.items():
            if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
                raise SettingsValidationError(
                    f"safety_permissions.user_permissions[{user!r}] must be list[str]"
                )
        out["user_permissions"] = up
    if "admin_users" in data:
        au = data["admin_users"]
        if not isinstance(au, list) or not all(isinstance(u, str) for u in au):
            raise SettingsValidationError("safety_permissions.admin_users must be list[str]")
        out["admin_users"] = au
    if not out:
        raise SettingsValidationError("safety_permissions payload empty")
    return out


def _validate_tool_security(value: Any) -> dict:
    data = _require_dict("tool_security", value)
    out: dict[str, Any] = {}
    list_str_fields = ("dangerous_patterns", "sensitive_file_patterns", "allowed_ssh_hosts",
                       "command_whitelist")
    for field in list_str_fields:
        if field in data:
            v = data[field]
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise SettingsValidationError(f"tool_security.{field} must be list[str]")
            out[field] = v
    if "base_directory" in data:
        v = data["base_directory"]
        if not isinstance(v, str):
            raise SettingsValidationError("tool_security.base_directory must be string")
        out["base_directory"] = v
    if "command_whitelist_enabled" in data:
        out["command_whitelist_enabled"] = _coerce_bool(
            data["command_whitelist_enabled"], "tool_security.command_whitelist_enabled"
        )
    if not out:
        raise SettingsValidationError("tool_security payload empty")
    return out


def _validate_monitoring_config(value: Any) -> dict:
    data = _require_dict("monitoring_config", value)
    # Convenience: when an SDUI form sends loop_protector fields at the top
    # level (because the form widget can only emit a flat dict), auto-wrap
    # them under "loop_protector" so the rest of the validator stays simple.
    _LP_FIELDS = ("cooldown_minutes", "max_auto_actions")
    if any(k in data for k in _LP_FIELDS) and "loop_protector" not in data:
        wrapped = {k: data[k] for k in _LP_FIELDS if k in data}
        data = {k: v for k, v in data.items() if k not in _LP_FIELDS}
        data["loop_protector"] = wrapped
    out: dict[str, Any] = {}
    if "rules" in data:
        rules = data["rules"]
        if not isinstance(rules, list):
            raise SettingsValidationError("monitoring_config.rules must be a list")
        cleaned_rules = []
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise SettingsValidationError(f"monitoring_config.rules[{i}] must be an object")
            name = rule.get("name")
            if not isinstance(name, str) or not name:
                raise SettingsValidationError(
                    f"monitoring_config.rules[{i}].name must be a non-empty string"
                )
            enabled = rule.get("enabled", True)
            if not isinstance(enabled, bool):
                raise SettingsValidationError(
                    f"monitoring_config.rules[{i}].enabled must be bool"
                )
            interval = rule.get("interval_seconds")
            try:
                interval = int(interval)
            except (TypeError, ValueError) as exc:
                raise SettingsValidationError(
                    f"monitoring_config.rules[{i}].interval_seconds must be int"
                ) from exc
            if interval < 60:
                raise SettingsValidationError(
                    f"monitoring_config.rules[{i}].interval_seconds must be >= 60"
                )
            cleaned_rules.append({"name": name, "enabled": enabled, "interval_seconds": interval})
        out["rules"] = cleaned_rules
    if "loop_protector" in data:
        lp = data["loop_protector"]
        if not isinstance(lp, dict):
            raise SettingsValidationError("monitoring_config.loop_protector must be an object")
        lp_out: dict[str, Any] = {}
        if "cooldown_minutes" in lp:
            v = lp["cooldown_minutes"]
            try:
                iv = int(v)
            except (TypeError, ValueError) as exc:
                raise SettingsValidationError(
                    "monitoring_config.loop_protector.cooldown_minutes must be int"
                ) from exc
            if iv < 0:
                raise SettingsValidationError(
                    "monitoring_config.loop_protector.cooldown_minutes must be >= 0"
                )
            lp_out["cooldown_minutes"] = iv
        if "max_auto_actions" in lp:
            v = lp["max_auto_actions"]
            try:
                iv = int(v)
            except (TypeError, ValueError) as exc:
                raise SettingsValidationError(
                    "monitoring_config.loop_protector.max_auto_actions must be int"
                ) from exc
            if iv < 0:
                raise SettingsValidationError(
                    "monitoring_config.loop_protector.max_auto_actions must be >= 0"
                )
            lp_out["max_auto_actions"] = iv
        out["loop_protector"] = lp_out
    if not out:
        raise SettingsValidationError("monitoring_config payload empty")
    return out


def _validate_scheduler_cron(value: Any) -> list:
    if not isinstance(value, list):
        raise SettingsValidationError("scheduler_cron must be a list")
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise SettingsValidationError(f"scheduler_cron[{i}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise SettingsValidationError(
                f"scheduler_cron[{i}].name must be a non-empty string"
            )
        schedule = item.get("schedule")
        if not isinstance(schedule, str) or not schedule:
            raise SettingsValidationError(
                f"scheduler_cron[{i}].schedule must be a non-empty string"
            )
        task = item.get("task")
        if not isinstance(task, str) or not task:
            raise SettingsValidationError(
                f"scheduler_cron[{i}].task must be a non-empty string"
            )
        enabled = _coerce_bool(item.get("enabled", True), f"scheduler_cron[{i}].enabled")
        job_id = item.get("id") or str(uuid.uuid4())
        entry: dict[str, Any] = {
            "id": job_id,
            "name": name,
            "schedule": schedule,
            "task": task,
            "enabled": enabled,
        }
        if "model" in item:
            entry["model"] = item["model"]
        out.append(entry)
    return out


def _validate_webhook_endpoints(value: Any) -> list:
    if not isinstance(value, list):
        raise SettingsValidationError("webhook_endpoints must be a list")
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise SettingsValidationError(f"webhook_endpoints[{i}] must be an object")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            raise SettingsValidationError(
                f"webhook_endpoints[{i}].url must be a non-empty string"
            )
        if not (url.startswith("http://") or url.startswith("https://")):
            raise SettingsValidationError(
                f"webhook_endpoints[{i}].url must start with http:// or https://"
            )
        event_type = item.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise SettingsValidationError(
                f"webhook_endpoints[{i}].event_type must be a non-empty string"
            )
        active = item.get("active", True)
        if not isinstance(active, bool):
            raise SettingsValidationError(f"webhook_endpoints[{i}].active must be bool")
        out.append({"url": url, "event_type": event_type, "active": active})
    return out


# ---------------------------------------------------------------------------
# Phase 3 helpers
# ---------------------------------------------------------------------------

def _int_in_range(value: Any, field: str, lo: int, hi: int) -> int:
    """Coerce value to int and validate it falls within [lo, hi]."""
    try:
        iv = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingsValidationError(f"{field} must be int") from exc
    if not (lo <= iv <= hi):
        raise SettingsValidationError(f"{field} must be between {lo} and {hi}")
    return iv


def _float_in_range(value: Any, field: str, lo: float, hi: float) -> float:
    """Coerce value to float and validate it falls within [lo, hi]."""
    try:
        fv = float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsValidationError(f"{field} must be a number") from exc
    if not (lo <= fv <= hi):
        raise SettingsValidationError(f"{field} must be between {lo} and {hi}")
    return fv


# ---------------------------------------------------------------------------
# Phase 3 validators
# ---------------------------------------------------------------------------

def _validate_memory_gc_config(value: Any) -> dict:
    data = _require_dict("memory_gc_config", value)
    out: dict[str, Any] = {}
    if "interval_seconds" in data:
        out["interval_seconds"] = _int_in_range(
            data["interval_seconds"], "memory_gc_config.interval_seconds", 60, 86400
        )
    if "decay_threshold" in data:
        out["decay_threshold"] = _float_in_range(
            data["decay_threshold"], "memory_gc_config.decay_threshold", 0.01, 1.0
        )
    if "max_cached_notes" in data:
        out["max_cached_notes"] = _int_in_range(
            data["max_cached_notes"], "memory_gc_config.max_cached_notes", 10, 10000
        )
    if "kg_max_age_days" in data:
        out["kg_max_age_days"] = _int_in_range(
            data["kg_max_age_days"], "memory_gc_config.kg_max_age_days", 1, 365
        )
    if "env_refresh_interval" in data:
        out["env_refresh_interval"] = _int_in_range(
            data["env_refresh_interval"], "memory_gc_config.env_refresh_interval", 1, 3600
        )
    if not out:
        raise SettingsValidationError("memory_gc_config payload empty")
    return out


def _validate_system_timeouts(value: Any) -> dict:
    data = _require_dict("system_timeouts", value)
    out: dict[str, Any] = {}
    _fields = (
        "tool_call", "llm_api", "ssh_command", "health_check",
        "pypi_check", "http_default", "skill_discovery",
    )
    for field in _fields:
        if field in data:
            out[field] = _int_in_range(
                data[field], f"system_timeouts.{field}", 1, 3600
            )
    if not out:
        raise SettingsValidationError("system_timeouts payload empty")
    return out


def _validate_retry_config(value: Any) -> dict:
    data = _require_dict("retry_config", value)
    out: dict[str, Any] = {}
    _retries_fields = ("max_retries", "llm_max_retries", "gateway_max_retries")
    for field in _retries_fields:
        if field in data:
            out[field] = _int_in_range(data[field], f"retry_config.{field}", 1, 50)
    _backoff_fields = ("base_backoff", "max_backoff")
    for field in _backoff_fields:
        if field in data:
            out[field] = _int_in_range(data[field], f"retry_config.{field}", 1, 600)
    if "health_check_interval" in data:
        out["health_check_interval"] = _int_in_range(
            data["health_check_interval"], "retry_config.health_check_interval", 5, 3600
        )
    if not out:
        raise SettingsValidationError("retry_config payload empty")
    return out


def _validate_limits_config(value: Any) -> dict:
    data = _require_dict("limits_config", value)
    out: dict[str, Any] = {}
    _int_fields: list[tuple[str, int, int]] = [
        ("max_tools", 1, 200),
        ("max_context_tokens", 100, 1_000_000),
        ("max_per_domain_skills", 1, 50),
        ("audit_log_recent", 1, 10000),
        ("embedding_cache_size", 10, 100_000),
        ("top_roles_limit", 1, 100),
        ("smart_retriever_token_budget", 100, 1_000_000),
        ("smart_retriever_limit", 1, 100),
    ]
    for field, lo, hi in _int_fields:
        if field in data:
            out[field] = _int_in_range(data[field], f"limits_config.{field}", lo, hi)
    if "low_performance_threshold" in data:
        out["low_performance_threshold"] = _float_in_range(
            data["low_performance_threshold"],
            "limits_config.low_performance_threshold",
            0.0, 1.0,
        )
    if not out:
        raise SettingsValidationError("limits_config payload empty")
    return out


def _validate_polling_config(value: Any) -> dict:
    data = _require_dict("polling_config", value)
    out: dict[str, Any] = {}
    _fields = (
        "signal_interval", "gmail_interval", "update_check_interval",
        "data_flush_interval", "auto_cleanup_interval",
    )
    for field in _fields:
        if field in data:
            out[field] = _int_in_range(
                data[field], f"polling_config.{field}", 1, 86400
            )
    if not out:
        raise SettingsValidationError("polling_config payload empty")
    return out


def _validate_agent_timeouts(value: Any) -> dict:
    data = _require_dict("agent_timeouts", value)
    out: dict[str, Any] = {}
    if "tool_timeout" in data:
        out["tool_timeout"] = _int_in_range(
            data["tool_timeout"], "agent_timeouts.tool_timeout", 1, 3600
        )
    if "chat_timeout" in data:
        out["chat_timeout"] = _int_in_range(
            data["chat_timeout"], "agent_timeouts.chat_timeout", 1, 3600
        )
    if "max_turns" in data:
        out["max_turns"] = _int_in_range(
            data["max_turns"], "agent_timeouts.max_turns", 1, 100
        )
    if not out:
        raise SettingsValidationError("agent_timeouts payload empty")
    return out


def _validate_logging_config(value: Any) -> dict:
    data = _require_dict("logging_config", value)
    out: dict[str, Any] = {}
    if "level" in data:
        v = data["level"]
        if not isinstance(v, str):
            raise SettingsValidationError("logging_config.level must be a string")
        normalized = v.strip().upper()
        if normalized not in _LOG_LEVELS:
            raise SettingsValidationError(
                f"logging_config.level must be one of {sorted(_LOG_LEVELS)}"
            )
        out["level"] = normalized
    if "format" in data:
        v = data["format"]
        if v not in _LOG_FORMATS:
            raise SettingsValidationError(
                f"logging_config.format must be one of {sorted(_LOG_FORMATS)}"
            )
        out["format"] = v
    if not out:
        raise SettingsValidationError("logging_config payload empty")
    return out
