import pytest
from pathlib import Path
from breadmind.core.protocols import PromptBlock, PromptContext
from breadmind.plugins.v2_builtin.prompt_builder.jinja_builder import JinjaPromptBuilder

@pytest.fixture
def builder():
    templates_dir = Path(__file__).resolve().parent.parent.parent / "src" / "breadmind" / "prompts"
    return JinjaPromptBuilder(templates_dir=templates_dir)

def test_build_returns_prompt_blocks(builder):
    ctx = PromptContext(persona_name="TestBot", language="en", provider_model="test-model")
    blocks = builder.build(ctx, provider="claude", persona="professional")
    assert isinstance(blocks, list)
    assert all(isinstance(b, PromptBlock) for b in blocks)
    assert len(blocks) > 0

def test_iron_laws_is_priority_zero(builder):
    ctx = PromptContext()
    blocks = builder.build(ctx, provider="claude")
    iron = [b for b in blocks if b.section == "iron_laws"]
    assert len(iron) == 1
    assert iron[0].priority == 0
    assert iron[0].cacheable is True

def test_identity_block_contains_persona_name(builder):
    ctx = PromptContext(persona_name="MyAgent")
    blocks = builder.build(ctx, provider="claude")
    identity = [b for b in blocks if b.section == "identity"]
    assert len(identity) == 1
    assert "MyAgent" in identity[0].content

def test_dynamic_blocks_not_cacheable(builder):
    ctx = PromptContext(os_info="Linux 6.1", current_date="2026-04-04")
    blocks = builder.build(ctx, provider="claude")
    env_blocks = [b for b in blocks if b.section == "env"]
    assert len(env_blocks) == 1
    assert env_blocks[0].cacheable is False

def test_rebuild_dynamic_returns_only_dynamic(builder):
    ctx = PromptContext(os_info="Linux 6.1", current_date="2026-04-04")
    builder.build(ctx, provider="claude")
    dynamic = builder.rebuild_dynamic(ctx)
    assert all(b.cacheable is False for b in dynamic)

def test_trim_to_budget_keeps_iron_laws(builder):
    ctx = PromptContext()
    blocks = builder.build(ctx, provider="claude")
    trimmed = builder.trim_to_budget(blocks, max_tokens=100)
    priorities = [b.priority for b in trimmed]
    assert 0 in priorities
    assert len(trimmed) <= len(blocks)
