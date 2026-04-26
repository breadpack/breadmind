"""Cross-provider audit: mid-list ``role="system"`` messages must reach the model.

P1 tool-recall wiring (``CoreAgent._do_recall`` → buffer drain in
``handle_message``) appends ``LLMMessage(role="system")`` after tool results,
so the messages list each provider receives may look like::

    [user, assistant(tool_calls), tool, system(prior_runs), user, ...]

Every provider adapter must route that mid-list system content to the model
in some reachable form (preserved, merged into the lead system slot, or
demoted to a user turn with a recall prefix). This test suite verifies the
behaviour without calling real APIs.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.llm.base import LLMMessage, ToolCall


# ---- Helpers ----------------------------------------------------------------


def _mid_list_messages() -> list[LLMMessage]:
    """Realistic P1 shape: system at front, recall system mid-list."""
    return [
        LLMMessage(role="system", content="LEAD_SYS"),
        LLMMessage(role="user", content="run the tool"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="tc_1", name="t", arguments={})],
        ),
        LLMMessage(role="tool", content="ok", tool_call_id="tc_1", name="t"),
        LLMMessage(role="system", content="RECALL_SYS"),
        LLMMessage(role="user", content="continue"),
    ]


# ---- Claude -----------------------------------------------------------------


class TestClaudeMidListSystem:
    """Claude adapter merges every system message into the ``system`` param."""

    def test_mid_list_system_merged_into_system_param(self):
        from breadmind.llm.claude import ClaudeProvider

        provider = ClaudeProvider(api_key="k", default_model="claude-sonnet-4-6")
        system_prompt, api_messages = provider._convert_messages(_mid_list_messages())

        assert system_prompt is not None
        assert "LEAD_SYS" in system_prompt
        assert "RECALL_SYS" in system_prompt
        # No system turn leaks into the messages list.
        assert all(m["role"] != "system" for m in api_messages)


# ---- Gemini -----------------------------------------------------------------


class TestGeminiMidListSystem:
    def test_mid_list_system_merged_into_system_instruction(self):
        from breadmind.llm.gemini import GeminiProvider

        provider = GeminiProvider(api_key="k")
        system_prompt, contents = provider._convert_messages(_mid_list_messages())

        assert system_prompt is not None
        assert "LEAD_SYS" in system_prompt
        assert "RECALL_SYS" in system_prompt
        # No "system" role leaked into the contents list (Gemini uses
        # user/model/function only).
        assert all(c.get("role") in {"user", "model", "function"} for c in contents)


# ---- Bedrock ----------------------------------------------------------------


class TestBedrockMidListSystem:
    def test_mid_list_system_appended_to_system_prompts(self):
        boto3 = pytest.importorskip("boto3")  # noqa: F841
        from breadmind.llm.bedrock import BedrockProvider

        with patch("boto3.Session"):
            provider = BedrockProvider(api_key="")
        converse, system_prompts = provider._convert_messages(_mid_list_messages())

        texts = [s["text"] for s in system_prompts]
        assert "LEAD_SYS" in texts
        assert "RECALL_SYS" in texts
        assert all(m["role"] != "system" for m in converse)


# ---- Ollama -----------------------------------------------------------------


class TestOllamaMidListSystem:
    """Ollama's chat API accepts mid-list system messages — preserved as-is."""

    @pytest.mark.asyncio
    async def test_mid_list_system_preserved_in_payload(self):
        from breadmind.llm.ollama import OllamaProvider

        provider = OllamaProvider(base_url="http://localhost:11434")

        captured: dict = {}

        class _Resp:
            status = 200

            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *a):
                return False

            async def json(self_inner):
                return {
                    "message": {"role": "assistant", "content": "ok"},
                    "done": True,
                    "eval_count": 1,
                    "prompt_eval_count": 1,
                }

        def _post(url, json=None, **kw):  # noqa: A002
            captured["body"] = json
            return _Resp()

        with patch("aiohttp.ClientSession.post", side_effect=_post):
            await provider.chat(_mid_list_messages())

        roles = [m["role"] for m in captured["body"]["messages"]]
        contents = [m["content"] for m in captured["body"]["messages"]]
        # Both system messages must be in the payload.
        assert roles.count("system") == 2
        assert "LEAD_SYS" in contents
        assert "RECALL_SYS" in contents


# ---- OpenAI-compatible (Grok / OpenAI / Groq / etc.) ------------------------


class TestOpenAICompatMidListSystem:
    """Mid-list system messages are merged into the lead system slot."""

    def _provider(self):
        from breadmind.llm.openai_compat import OpenAICompatibleProvider

        class _MockProvider(OpenAICompatibleProvider):
            PROVIDER_NAME = "mock"
            BASE_URL = "https://api.example.com/v1"
            DEFAULT_MODEL = "mock-1"

        with patch("openai.AsyncOpenAI"):
            return _MockProvider(api_key="k")

    def test_normalize_messages_collapses_system(self):
        provider = self._provider()
        normalized = provider._normalize_messages(_mid_list_messages())

        # First message is the merged system.
        assert normalized[0].role == "system"
        assert "LEAD_SYS" in normalized[0].content
        assert "RECALL_SYS" in normalized[0].content
        # No other system messages remain.
        assert sum(1 for m in normalized if m.role == "system") == 1

    def test_convert_messages_sends_one_lead_system(self):
        provider = self._provider()
        api_messages = provider._convert_messages(_mid_list_messages())

        # API payload starts with the consolidated system message and contains
        # exactly one such turn.
        assert api_messages[0]["role"] == "system"
        assert "LEAD_SYS" in api_messages[0]["content"]
        assert "RECALL_SYS" in api_messages[0]["content"]
        assert sum(1 for m in api_messages if m["role"] == "system") == 1

    @pytest.mark.asyncio
    async def test_chat_payload_contains_recall_system_text(self):
        """End-to-end: the body sent to the OpenAI client carries RECALL_SYS."""
        from breadmind.llm.openai_compat import OpenAICompatibleProvider

        class _MockProvider(OpenAICompatibleProvider):
            PROVIDER_NAME = "mock"
            BASE_URL = "https://api.example.com/v1"
            DEFAULT_MODEL = "mock-1"

        with patch("openai.AsyncOpenAI"):
            provider = _MockProvider(api_key="k")

        # Mock the response.
        mock_choice = MagicMock()
        mock_choice.message.content = "done"
        mock_choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 1
        mock_response.usage.completion_tokens = 1

        provider._client.chat.completions.create = AsyncMock(return_value=mock_response)

        await provider.chat(_mid_list_messages())

        kwargs = provider._client.chat.completions.create.call_args.kwargs
        body_messages = kwargs["messages"]
        # All system fragments survived in some form.
        joined = json.dumps(body_messages)
        assert "LEAD_SYS" in joined
        assert "RECALL_SYS" in joined


# ---- CLI --------------------------------------------------------------------


class TestCLIMidListSystem:
    """CLI demotes mid-list system → user(``[system-recall] ...``)."""

    def test_normalize_demotes_mid_list_system_to_user(self):
        from breadmind.llm.cli import CLIProvider

        provider = CLIProvider(command="echo", args=[])
        normalized = provider._normalize_messages(_mid_list_messages())

        # Lead system stays as a system role.
        assert normalized[0].role == "system"
        assert "LEAD_SYS" in normalized[0].content

        # The mid-list RECALL_SYS becomes a user turn with the recall prefix.
        recall_users = [
            m for m in normalized
            if m.role == "user" and m.content and m.content.startswith("[system-recall]")
        ]
        assert len(recall_users) == 1
        assert "RECALL_SYS" in recall_users[0].content

        # No system message remains anywhere except position 0.
        assert sum(1 for m in normalized if m.role == "system") == 1

    def test_build_prompt_carries_recall_text(self):
        from breadmind.llm.cli import CLIProvider

        provider = CLIProvider(command="echo", args=[])
        prompt = provider._build_prompt(_mid_list_messages(), tools=None)
        # The lead system is intentionally dropped (passed via CLI flags),
        # but the mid-list recall must still reach the subprocess.
        assert "[system-recall] RECALL_SYS" in prompt

    @pytest.mark.asyncio
    async def test_chat_subprocess_receives_recall(self):
        """End-to-end: subprocess argv carries the [system-recall] segment."""
        from breadmind.llm.cli import CLIProvider

        provider = CLIProvider(command="claude", args=["-p"])

        captured_argv: list[str] = []

        async def _fake_create_subprocess_exec(*args, **kwargs):
            captured_argv.extend(args)
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            return mock_proc

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=_fake_create_subprocess_exec,
        ):
            await provider.chat(_mid_list_messages())

        # Last arg is the prompt text.
        prompt = captured_argv[-1]
        assert "[system-recall] RECALL_SYS" in prompt
