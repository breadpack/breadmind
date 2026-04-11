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
    assert not is_allowed_key("vault:something")  # Phase 1 미포함
    assert not is_allowed_key("safety_blacklist")  # Phase 2


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
