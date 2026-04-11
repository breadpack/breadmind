import pytest
from breadmind.sdui.settings_schema import (
    is_allowed_key,
    is_credential_key,
    validate_value,
    requires_restart,
    mask_credential,
    SettingsValidationError,
)


def test_is_allowed_key_phase1_keys():
    assert is_allowed_key("llm")
    assert is_allowed_key("persona")
    assert is_allowed_key("custom_prompts")
    assert is_allowed_key("custom_instructions")
    assert is_allowed_key("embedding_config")
    assert is_allowed_key("apikey:GEMINI_API_KEY")
    assert is_allowed_key("apikey:ANTHROPIC_API_KEY")


def test_is_allowed_key_rejects_unknown():
    assert not is_allowed_key("malicious_key")
    assert not is_allowed_key("apikey:UNKNOWN_KEY")
    assert not is_allowed_key("vault:something")
    assert not is_allowed_key("totally_unknown_key")


def test_is_credential_key():
    assert is_credential_key("apikey:GEMINI_API_KEY")
    assert not is_credential_key("llm")
    assert not is_credential_key("persona")


def test_validate_llm_accepts_partial():
    out = validate_value("llm", {"default_provider": "gemini"})
    assert out == {"default_provider": "gemini"}


def test_validate_llm_max_turns_range():
    validate_value("llm", {"tool_call_max_turns": 25})  # ok
    with pytest.raises(SettingsValidationError):
        validate_value("llm", {"tool_call_max_turns": 0})
    with pytest.raises(SettingsValidationError):
        validate_value("llm", {"tool_call_max_turns": 100})


def test_validate_persona_preset_enum():
    validate_value("persona", {"preset": "professional"})
    with pytest.raises(SettingsValidationError):
        validate_value("persona", {"preset": "rude"})


def test_validate_custom_instructions_length():
    validate_value("custom_instructions", "x" * 100)
    with pytest.raises(SettingsValidationError):
        validate_value("custom_instructions", "x" * 9000)


def test_validate_apikey_non_empty():
    validate_value("apikey:GEMINI_API_KEY", "abc123")
    with pytest.raises(SettingsValidationError):
        validate_value("apikey:GEMINI_API_KEY", "")
    with pytest.raises(SettingsValidationError):
        validate_value("apikey:GEMINI_API_KEY", None)


def test_validate_embedding_provider_enum():
    validate_value("embedding_config", {"provider": "fastembed"})
    with pytest.raises(SettingsValidationError):
        validate_value("embedding_config", {"provider": "bogus"})


def test_requires_restart_only_embedding():
    assert requires_restart("embedding_config")
    assert not requires_restart("llm")
    assert not requires_restart("apikey:GEMINI_API_KEY")


def test_mask_credential_short():
    assert mask_credential("abcd") == "●●●●"
    assert mask_credential("") == "미설정"
    assert mask_credential(None) == "미설정"


def test_mask_credential_long():
    masked = mask_credential("sk-1234567890abcdef")
    assert masked.startswith("●")
    assert masked.endswith("cdef")


# ---------------------------------------------------------------------------
# Phase 2 keys: is_allowed_key
# ---------------------------------------------------------------------------

def test_is_allowed_key_phase2_keys():
    phase2_keys = [
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
    ]
    for key in phase2_keys:
        assert is_allowed_key(key), f"expected {key!r} to be allowed"


def test_phase2_keys_no_restart():
    phase2_keys = [
        "mcp", "mcp_servers", "skill_markets", "safety_blacklist",
        "safety_approval", "safety_permissions", "tool_security",
        "monitoring_config", "scheduler_cron", "webhook_endpoints",
    ]
    for key in phase2_keys:
        assert not requires_restart(key), f"{key!r} should not require restart"


def test_phase2_keys_not_credential():
    phase2_keys = [
        "mcp", "mcp_servers", "skill_markets", "safety_blacklist",
        "safety_approval", "safety_permissions", "tool_security",
        "monitoring_config", "scheduler_cron", "webhook_endpoints",
    ]
    for key in phase2_keys:
        assert not is_credential_key(key)


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------

def test_validate_mcp_valid_partial():
    out = validate_value("mcp", {"auto_discover": True})
    assert out == {"auto_discover": True}


def test_validate_mcp_max_restart_attempts():
    out = validate_value("mcp", {"max_restart_attempts": 3})
    assert out["max_restart_attempts"] == 3


def test_validate_mcp_both_fields():
    out = validate_value("mcp", {"auto_discover": False, "max_restart_attempts": 0})
    assert out == {"auto_discover": False, "max_restart_attempts": 0}


def test_validate_mcp_empty_payload_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp", {})


def test_validate_mcp_auto_discover_not_bool_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp", {"auto_discover": "yes"})


def test_validate_mcp_max_restart_attempts_negative_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp", {"max_restart_attempts": -1})


def test_validate_mcp_not_dict_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp", "string")


# ---------------------------------------------------------------------------
# mcp_servers
# ---------------------------------------------------------------------------

def test_validate_mcp_servers_valid():
    servers = [
        {"name": "my-server", "command": "/usr/bin/tool", "args": ["--verbose"], "env": {"X": "1"}, "enabled": True}
    ]
    out = validate_value("mcp_servers", servers)
    assert len(out) == 1
    assert out[0]["name"] == "my-server"


def test_validate_mcp_servers_minimal():
    out = validate_value("mcp_servers", [{"name": "s", "command": "cmd"}])
    assert out[0]["args"] == []
    assert out[0]["env"] == {}
    assert out[0]["enabled"] is True


def test_validate_mcp_servers_empty_list_ok():
    out = validate_value("mcp_servers", [])
    assert out == []


def test_validate_mcp_servers_duplicate_name_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp_servers", [
            {"name": "dup", "command": "cmd1"},
            {"name": "dup", "command": "cmd2"},
        ])


def test_validate_mcp_servers_missing_command_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp_servers", [{"name": "s"}])


def test_validate_mcp_servers_empty_name_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp_servers", [{"name": "", "command": "cmd"}])


def test_validate_mcp_servers_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("mcp_servers", {"name": "s", "command": "c"})


# ---------------------------------------------------------------------------
# skill_markets
# ---------------------------------------------------------------------------

def test_validate_skill_markets_valid():
    out = validate_value("skill_markets", [
        {"name": "official", "type": "skills_sh", "enabled": True}
    ])
    assert out[0]["type"] == "skills_sh"


def test_validate_skill_markets_defaults():
    out = validate_value("skill_markets", [{"name": "m", "type": "clawhub"}])
    assert out[0]["enabled"] is True


def test_validate_skill_markets_empty_ok():
    assert validate_value("skill_markets", []) == []


def test_validate_skill_markets_invalid_type_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("skill_markets", [{"name": "m", "type": "bogus"}])


def test_validate_skill_markets_duplicate_name_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("skill_markets", [
            {"name": "dup", "type": "skills_sh"},
            {"name": "dup", "type": "clawhub"},
        ])


def test_validate_skill_markets_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("skill_markets", "not-a-list")


# ---------------------------------------------------------------------------
# safety_blacklist
# ---------------------------------------------------------------------------

def test_validate_safety_blacklist_valid():
    out = validate_value("safety_blacklist", {"shell": ["rm", "curl"], "k8s": ["delete"]})
    assert out["shell"] == ["rm", "curl"]


def test_validate_safety_blacklist_empty_ok():
    assert validate_value("safety_blacklist", {}) == {}


def test_validate_safety_blacklist_not_dict_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_blacklist", ["rm"])


def test_validate_safety_blacklist_value_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_blacklist", {"shell": "rm"})


def test_validate_safety_blacklist_tool_name_not_str_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_blacklist", {"shell": [123]})


def test_validate_safety_blacklist_empty_tool_name_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_blacklist", {"shell": [""]})


# ---------------------------------------------------------------------------
# safety_approval
# ---------------------------------------------------------------------------

def test_validate_safety_approval_valid():
    out = validate_value("safety_approval", ["reboot", "delete_all"])
    assert out == ["reboot", "delete_all"]


def test_validate_safety_approval_empty_list_ok():
    assert validate_value("safety_approval", []) == []


def test_validate_safety_approval_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_approval", "reboot")


def test_validate_safety_approval_empty_string_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_approval", [""])


def test_validate_safety_approval_non_string_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_approval", [42])


# ---------------------------------------------------------------------------
# safety_permissions
# ---------------------------------------------------------------------------

def test_validate_safety_permissions_user_permissions():
    out = validate_value("safety_permissions", {"user_permissions": {"alice": ["read", "write"]}})
    assert out["user_permissions"]["alice"] == ["read", "write"]


def test_validate_safety_permissions_admin_users():
    out = validate_value("safety_permissions", {"admin_users": ["alice", "bob"]})
    assert out["admin_users"] == ["alice", "bob"]


def test_validate_safety_permissions_empty_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_permissions", {})


def test_validate_safety_permissions_not_dict_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_permissions", ["alice"])


def test_validate_safety_permissions_user_permissions_not_dict_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_permissions", {"user_permissions": ["alice"]})


def test_validate_safety_permissions_admin_users_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("safety_permissions", {"admin_users": "alice"})


# ---------------------------------------------------------------------------
# tool_security
# ---------------------------------------------------------------------------

def test_validate_tool_security_valid():
    out = validate_value("tool_security", {
        "dangerous_patterns": ["rm -rf"],
        "command_whitelist_enabled": True,
        "base_directory": "/home/user",
    })
    assert out["base_directory"] == "/home/user"
    assert out["command_whitelist_enabled"] is True


def test_validate_tool_security_empty_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("tool_security", {})


def test_validate_tool_security_not_dict_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("tool_security", "bad")


def test_validate_tool_security_dangerous_patterns_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("tool_security", {"dangerous_patterns": "rm -rf"})


def test_validate_tool_security_command_whitelist_enabled_not_bool_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("tool_security", {"command_whitelist_enabled": "true"})


# ---------------------------------------------------------------------------
# monitoring_config
# ---------------------------------------------------------------------------

def test_validate_monitoring_config_rules_valid():
    out = validate_value("monitoring_config", {
        "rules": [{"name": "cpu", "enabled": True, "interval_seconds": 60}]
    })
    assert out["rules"][0]["name"] == "cpu"


def test_validate_monitoring_config_loop_protector():
    out = validate_value("monitoring_config", {
        "loop_protector": {"cooldown_minutes": 5, "max_auto_actions": 10}
    })
    assert out["loop_protector"]["cooldown_minutes"] == 5


def test_validate_monitoring_config_empty_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("monitoring_config", {})


def test_validate_monitoring_config_interval_too_low_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("monitoring_config", {
            "rules": [{"name": "r", "enabled": True, "interval_seconds": 59}]
        })


def test_validate_monitoring_config_cooldown_negative_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("monitoring_config", {
            "loop_protector": {"cooldown_minutes": -1}
        })


# ---------------------------------------------------------------------------
# scheduler_cron
# ---------------------------------------------------------------------------

def test_validate_scheduler_cron_valid():
    out = validate_value("scheduler_cron", [
        {"name": "daily", "schedule": "0 0 * * *", "task": "cleanup"}
    ])
    assert out[0]["name"] == "daily"
    assert out[0]["enabled"] is True
    assert "id" in out[0]


def test_validate_scheduler_cron_with_id():
    out = validate_value("scheduler_cron", [
        {"id": "my-id", "name": "t", "schedule": "* * * * *", "task": "ping"}
    ])
    assert out[0]["id"] == "my-id"


def test_validate_scheduler_cron_empty_list_ok():
    assert validate_value("scheduler_cron", []) == []


def test_validate_scheduler_cron_missing_name_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("scheduler_cron", [{"schedule": "* * * * *", "task": "x"}])


def test_validate_scheduler_cron_empty_schedule_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("scheduler_cron", [{"name": "t", "schedule": "", "task": "x"}])


def test_validate_scheduler_cron_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("scheduler_cron", {"name": "t"})


# ---------------------------------------------------------------------------
# webhook_endpoints
# ---------------------------------------------------------------------------

def test_validate_webhook_endpoints_valid():
    out = validate_value("webhook_endpoints", [
        {"url": "https://example.com/hook", "event_type": "alert"}
    ])
    assert out[0]["active"] is True


def test_validate_webhook_endpoints_http_ok():
    out = validate_value("webhook_endpoints", [
        {"url": "http://internal/hook", "event_type": "deploy"}
    ])
    assert out[0]["url"] == "http://internal/hook"


def test_validate_webhook_endpoints_empty_ok():
    assert validate_value("webhook_endpoints", []) == []


def test_validate_webhook_endpoints_bad_url_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("webhook_endpoints", [
            {"url": "ftp://bad.com/hook", "event_type": "x"}
        ])


def test_validate_webhook_endpoints_missing_event_type_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("webhook_endpoints", [{"url": "https://example.com/h"}])


def test_validate_webhook_endpoints_not_list_raises():
    with pytest.raises(SettingsValidationError):
        validate_value("webhook_endpoints", {"url": "https://x.com"})
