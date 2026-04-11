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


def is_allowed_key(key: str) -> bool:
    if key in {"llm", "persona", "custom_prompts", "custom_instructions", "embedding_config"}:
        return True
    if key in _PHASE2_KEYS:
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
        v = data["auto_discover"]
        if not isinstance(v, bool):
            raise SettingsValidationError("mcp.auto_discover must be bool")
        out["auto_discover"] = v
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
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise SettingsValidationError(f"skill_markets[{i}].enabled must be bool")
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
        v = data["command_whitelist_enabled"]
        if not isinstance(v, bool):
            raise SettingsValidationError("tool_security.command_whitelist_enabled must be bool")
        out["command_whitelist_enabled"] = v
    if not out:
        raise SettingsValidationError("tool_security payload empty")
    return out


def _validate_monitoring_config(value: Any) -> dict:
    data = _require_dict("monitoring_config", value)
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
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise SettingsValidationError(f"scheduler_cron[{i}].enabled must be bool")
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
