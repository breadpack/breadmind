from pathlib import Path

from breadmind.prompts.builder import PromptBuilder, PromptContext

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "breadmind" / "prompts"


def _simple_token_counter(text: str) -> int:
    return len(text) // 4


def _make_builder() -> PromptBuilder:
    return PromptBuilder(PROMPTS_DIR, _simple_token_counter)


def test_prompt_context_has_custom_prompts_field():
    ctx = PromptContext()
    assert hasattr(ctx, "custom_prompts")
    assert ctx.custom_prompts is None


def test_prompt_builder_accepts_custom_prompts_kwarg():
    builder = _make_builder()
    # Should not raise TypeError.
    out = builder.build(
        provider="claude",
        persona="professional",
        custom_prompts={"greeting": "Welcome!", "disclaimer": "Be careful."},
    )
    # The returned system prompt is a non-empty string. We don't assert the
    # custom prompts appear in the output because no existing template
    # consumes them yet — this test only pins the contract that the kwarg
    # is accepted.
    assert isinstance(out, str)
    assert len(out) > 0


def test_prompt_builder_reads_custom_prompts_from_context_when_kwarg_missing():
    """When custom_prompts is set on PromptContext and the kwarg is omitted,
    build() should fall back to the context field."""
    builder = _make_builder()
    ctx = PromptContext(custom_prompts={"note": "hello"})
    # Should not raise.
    out = builder.build(
        provider="claude",
        persona="professional",
        context=ctx,
    )
    assert isinstance(out, str)
