"""Tests for breadmind.hooks.condition.matches_condition."""
from __future__ import annotations


from breadmind.hooks.condition import matches_condition
from breadmind.hooks.events import HookEvent, HookPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload(
    event: HookEvent = HookEvent.PRE_TOOL_USE,
    **data,
) -> HookPayload:
    return HookPayload(event=event, data=data)


# ---------------------------------------------------------------------------
# None condition — always True
# ---------------------------------------------------------------------------

def test_none_condition_returns_true():
    payload = _payload(tool_name="Bash", tool_input="ls -la")
    assert matches_condition(None, payload) is True


# ---------------------------------------------------------------------------
# Tool pattern
# ---------------------------------------------------------------------------

class TestToolPattern:
    def test_exact_tool_name_match(self):
        payload = _payload(tool_name="Bash", tool_input="git status")
        assert matches_condition("Bash(git status)", payload) is True

    def test_tool_name_mismatch(self):
        payload = _payload(tool_name="Write", tool_input="git status")
        assert matches_condition("Bash(git status)", payload) is False

    def test_tool_arg_wildcard(self):
        payload = _payload(tool_name="Bash", tool_input="git commit -m 'msg'")
        assert matches_condition("Bash(git *)", payload) is True

    def test_tool_arg_wildcard_no_match(self):
        payload = _payload(tool_name="Bash", tool_input="ls -la")
        assert matches_condition("Bash(git *)", payload) is False

    def test_tool_name_only_no_parens(self):
        payload = _payload(tool_name="Bash", tool_input="anything")
        assert matches_condition("Bash", payload) is True

    def test_tool_name_only_no_parens_mismatch(self):
        payload = _payload(tool_name="Write", tool_input="anything")
        assert matches_condition("Bash", payload) is False

    def test_tool_name_only_no_tool_in_payload(self):
        payload = _payload()  # no tool_name key
        assert matches_condition("Bash", payload) is False

    def test_tool_pattern_no_tool_input_in_payload(self):
        # Has tool_name but no tool_input; pattern with args should not match
        payload = HookPayload(event=HookEvent.PRE_TOOL_USE, data={"tool_name": "Bash"})
        assert matches_condition("Bash(git *)", payload) is False

    def test_tool_wildcard_arg(self):
        payload = _payload(tool_name="Write", tool_input="/etc/passwd")
        assert matches_condition("Write(*)", payload) is True

    def test_tool_question_mark_wildcard(self):
        payload = _payload(tool_name="Bash", tool_input="git")
        assert matches_condition("Bash(gi?)", payload) is True

    def test_tool_case_sensitive_name(self):
        payload = _payload(tool_name="bash", tool_input="ls")
        assert matches_condition("Bash(ls)", payload) is False


# ---------------------------------------------------------------------------
# Data field match
# ---------------------------------------------------------------------------

class TestDataFieldMatch:
    def test_simple_field_match(self):
        payload = _payload(channel_id="general")
        assert matches_condition("data.channel_id=general", payload) is True

    def test_simple_field_no_match(self):
        payload = _payload(channel_id="random")
        assert matches_condition("data.channel_id=general", payload) is False

    def test_simple_field_missing_key(self):
        payload = _payload()
        assert matches_condition("data.channel_id=general", payload) is False

    def test_nested_field_match(self):
        payload = HookPayload(
            event=HookEvent.PRE_TOOL_USE,
            data={"user": {"role": "admin"}},
        )
        assert matches_condition("data.user.role=admin", payload) is True

    def test_nested_field_no_match(self):
        payload = HookPayload(
            event=HookEvent.PRE_TOOL_USE,
            data={"user": {"role": "viewer"}},
        )
        assert matches_condition("data.user.role=admin", payload) is False

    def test_nested_field_missing_intermediate(self):
        payload = HookPayload(
            event=HookEvent.PRE_TOOL_USE,
            data={"user": "not_a_dict"},
        )
        assert matches_condition("data.user.role=admin", payload) is False

    def test_deeply_nested_field(self):
        payload = HookPayload(
            event=HookEvent.PRE_TOOL_USE,
            data={"a": {"b": {"c": "value"}}},
        )
        assert matches_condition("data.a.b.c=value", payload) is True

    def test_value_with_spaces(self):
        # The regex captures everything after the first '='
        payload = _payload(message="hello world")
        assert matches_condition("data.message=hello world", payload) is True


# ---------------------------------------------------------------------------
# Event match
# ---------------------------------------------------------------------------

class TestEventMatch:
    def test_event_match(self):
        payload = _payload(event=HookEvent.PRE_TOOL_USE)
        assert matches_condition("event=pre_tool_use", payload) is True

    def test_event_no_match(self):
        payload = _payload(event=HookEvent.POST_TOOL_USE)
        assert matches_condition("event=pre_tool_use", payload) is False

    def test_event_messenger_received(self):
        payload = _payload(event=HookEvent.MESSENGER_RECEIVED)
        assert matches_condition("event=messenger_received", payload) is True

    def test_event_stop(self):
        payload = _payload(event=HookEvent.STOP)
        assert matches_condition("event=stop", payload) is True


# ---------------------------------------------------------------------------
# NOT prefix
# ---------------------------------------------------------------------------

class TestNotPrefix:
    def test_not_tool_pattern_inverts_match(self):
        payload = _payload(tool_name="Bash", tool_input="rm -rf /")
        assert matches_condition("!Bash(rm *)", payload) is False

    def test_not_tool_pattern_when_no_match(self):
        payload = _payload(tool_name="Bash", tool_input="ls")
        assert matches_condition("!Bash(rm *)", payload) is True

    def test_not_data_field_match(self):
        payload = _payload(channel_id="general")
        assert matches_condition("!data.channel_id=general", payload) is False

    def test_not_data_field_no_match(self):
        payload = _payload(channel_id="random")
        assert matches_condition("!data.channel_id=general", payload) is True

    def test_not_event_match(self):
        payload = _payload(event=HookEvent.PRE_TOOL_USE)
        assert matches_condition("!event=pre_tool_use", payload) is False

    def test_not_event_no_match(self):
        payload = _payload(event=HookEvent.POST_TOOL_USE)
        assert matches_condition("!event=pre_tool_use", payload) is True

    def test_not_none_condition(self):
        # None always returns True; NOT cannot be applied to None directly
        # (None is not a string, so this tests the None branch)
        payload = _payload()
        assert matches_condition(None, payload) is True


# ---------------------------------------------------------------------------
# OR array composition
# ---------------------------------------------------------------------------

class TestOrArray:
    def test_or_first_matches(self):
        payload = _payload(tool_name="Bash", tool_input="ls")
        assert matches_condition(["Bash(*)", "Write(*)"], payload) is True

    def test_or_second_matches(self):
        payload = _payload(tool_name="Write", tool_input="/tmp/foo")
        assert matches_condition(["Bash(*)", "Write(*)"], payload) is True

    def test_or_none_matches(self):
        payload = _payload(tool_name="Read", tool_input="/tmp/foo")
        assert matches_condition(["Bash(*)", "Write(*)"], payload) is False

    def test_or_empty_list(self):
        payload = _payload(tool_name="Bash", tool_input="ls")
        assert matches_condition([], payload) is False

    def test_or_single_element_list(self):
        payload = _payload(tool_name="Bash", tool_input="ls")
        assert matches_condition(["Bash(ls)"], payload) is True

    def test_or_with_not_and_positive(self):
        payload = _payload(tool_name="Bash", tool_input="ls")
        # !Bash(rm *) is True (ls != rm *), Bash(ls) is also True
        assert matches_condition(["!Bash(rm *)", "Bash(ls)"], payload) is True

    def test_or_mixed_event_and_tool(self):
        payload = _payload(event=HookEvent.PRE_TOOL_USE, tool_name="Bash", tool_input="ls")
        assert matches_condition(["event=pre_tool_use", "Write(*)"], payload) is True

    def test_or_mixed_no_match(self):
        payload = _payload(event=HookEvent.POST_TOOL_USE, tool_name="Read", tool_input="foo")
        assert matches_condition(["event=pre_tool_use", "Write(*)"], payload) is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string_condition(self):
        # Empty string doesn't match any known pattern — should return False
        payload = _payload()
        assert matches_condition("", payload) is False

    def test_tool_pattern_empty_parens(self):
        # "Bash()" — arg pattern is empty string; tool_input must be empty string
        payload = _payload(tool_name="Bash", tool_input="")
        assert matches_condition("Bash()", payload) is True

    def test_tool_pattern_empty_parens_non_empty_input(self):
        payload = _payload(tool_name="Bash", tool_input="something")
        assert matches_condition("Bash()", payload) is False

    def test_data_field_value_with_equals(self):
        # Value itself contains '=' — regex captures up to end, so should work
        payload = _payload(expr="a=b")
        assert matches_condition("data.expr=a=b", payload) is True

    def test_data_field_numeric_value_as_string(self):
        # All comparisons are string-based
        payload = HookPayload(
            event=HookEvent.PRE_TOOL_USE,
            data={"count": 42},
        )
        # 42 != "42" as string comparison
        assert matches_condition("data.count=42", payload) is False

    def test_not_double_negation_not_supported(self):
        # "!!" is not a special double-negation; inner string is "!Bash(*)"
        # which would be a NOT of Bash(*) — this test ensures no crash
        payload = _payload(tool_name="Bash", tool_input="ls")
        # "!" prefix strips once; inner "!Bash(*)" is NOT Bash(*) => False for Bash ls
        # outer NOT inverts => True
        result = matches_condition("!!Bash(*)", payload)
        assert isinstance(result, bool)
